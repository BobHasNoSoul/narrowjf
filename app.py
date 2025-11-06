from flask import Flask, render_template, request, redirect, url_for, session, Response
import requests

app = Flask(__name__)
app.secret_key = 'YOURSUPERSECRETKEYHERE'

JELLYFIN_SERVER = "http://YOURSERVERLANIPHERE:8096"
DEVICE_ID = "narrowjf"
DEFAULT_PAGE_SIZE = 25
ITEMS_TIMEOUT = 30
SEARCH_TIMEOUT = 20


def jellyfin_api(endpoint, method="GET", data=None, params=None, token=None, timeout=None):
    base_auth = f'MediaBrowser Client="Narrow Jellyfin Client", Device="narrowjf", DeviceId="{DEVICE_ID}", Version="1.0"'
    if token:
        base_auth += f', Token="{token}"'
    headers = {'X-Emby-Authorization': base_auth}
    if data is not None:
        headers['Content-Type'] = 'application/json'

    url = f"{JELLYFIN_SERVER}{endpoint}"
    try:
        if method == "POST":
            r = requests.post(url, headers=headers, json=data, params=params,
                              verify=False, timeout=timeout or SEARCH_TIMEOUT)
        else:
            r = requests.get(url, headers=headers, params=params,
                             verify=False, timeout=timeout or ITEMS_TIMEOUT)
        r.raise_for_status()
        return r.json() if r.text else {}
    except requests.RequestException as e:
        print(f"API Error on {endpoint}: {e}")
        return {"error": str(e)}


# ----------------------------------------------------------------------
# LOGIN
# ----------------------------------------------------------------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        auth_data = {"Username": username, "Pw": password}
        result = jellyfin_api("/Users/AuthenticateByName", method="POST", data=auth_data)
        if isinstance(result, dict) and "AccessToken" in result:
            session['user_id'] = result['User']['Id']
            session['access_token'] = result['AccessToken']
            return redirect(url_for('libraries'))
        return render_template('login.html', error="Invalid login.")
    return render_template('login.html')


# ----------------------------------------------------------------------
# LIBRARIES (Live TV support)
# ----------------------------------------------------------------------
@app.route('/libraries')
def libraries():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    result = jellyfin_api(f"/Users/{session['user_id']}/Views", token=session['access_token'])
    if isinstance(result, dict) and 'error' in result:
        return f"Error fetching libraries: {result['error']}"

    libs = sorted(result.get('Items', []), key=lambda x: x.get('Name', '').lower())
    return render_template('libraries.html', libraries=libs)


# ----------------------------------------------------------------------
# ITEMS (FULL SUPPORT: Movies + TV + LIVE TV)
# ----------------------------------------------------------------------
@app.route('/items/<parent_id>')
def items(parent_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    page = int(request.args.get('page', 0))
    page_size = int(request.args.get('page_size', DEFAULT_PAGE_SIZE))
    start_index = page * page_size
    library_type = request.args.get('library_type')

    # ===== LIVE TV / NORMAL LIBRARIES =====
    if library_type == 'movies':
        include_types = "Movie"
    elif library_type == 'tvshows':
        include_types = "Series,Season"
    elif library_type == 'livetv':  # 🔥 LIVE TV
        include_types = "Channel"
    else:
        include_types = "Series,Season,Episode,Movie,Audio,Channel,Program"

    # ===== INSIDE FOLDERS: Auto-detect what to show =====
    parent_info = jellyfin_api(f"/Items/{parent_id}", token=session['access_token'])
    parent_type = parent_info.get('Type') if isinstance(parent_info, dict) else None

    if parent_type == 'Season':
        include_types = "Episode"
    elif parent_type == 'Channel':  # 🔥 INSIDE CHANNEL = PROGRAMS
        include_types = "Program"
    elif parent_type == 'Series':
        include_types = "Season"

    params = {
        "ParentId": parent_id,
        "startIndex": start_index,
        "limit": page_size,
        "Recursive": "false",
        "IncludeItemTypes": include_types,
        "SortBy": "SortName",
        "SortOrder": "Ascending",
        "Fields": "BasicSyncInfo,ImageTags,ParentIndexNumber,IndexNumber,PremiereDate,ChannelId,TimerId",
        "ImageTypeLimit": 1,
        "UserId": session['user_id']
    }

    result = jellyfin_api("/Items", params=params, token=session['access_token'])
    if isinstance(result, dict) and 'error' in result:
        return f"Error fetching items: {result['error']}"

    items_list = result.get('Items', [])
    has_prev = page > 0
    has_next = len(items_list) == page_size

    return render_template(
        'items.html',
        items=items_list,
        parent_id=parent_id,
        page=page,
        page_size=page_size,
        has_prev=has_prev,
        has_next=has_next,
        library_type=library_type,
        search_query=None,
        JELLYFIN_SERVER=JELLYFIN_SERVER
    )


# ----------------------------------------------------------------------
# SEARCH (Added Program for Live TV)
# ----------------------------------------------------------------------
@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    query = request.args.get('query')
    if not query:
        return redirect(url_for('libraries'))

    page = int(request.args.get('page', 0))
    page_size = int(request.args.get('page_size', DEFAULT_PAGE_SIZE))
    start_index = page * page_size

    params = {
        "searchTerm": query,
        "SortBy": "SortName",
        "SortOrder": "Ascending",
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Series,Episode,Audio,Channel,Program",  # 🔥 Added Channel,Program
        "startIndex": start_index,
        "limit": page_size,
        "userId": session['user_id']
    }

    result = jellyfin_api("/Items", params=params, token=session['access_token'])
    if isinstance(result, dict) and 'error' in result:
        return f"Error searching: {result['error']}"

    items_list = result.get('Items', [])
    has_prev = page > 0
    has_next = len(items_list) == page_size

    return render_template(
        'items.html',
        items=items_list,
        parent_id=None,
        search_query=query,
        page=page,
        page_size=page_size,
        has_prev=has_prev,
        has_next=has_next,
        library_type=None,
        JELLYFIN_SERVER=JELLYFIN_SERVER
    )


# ----------------------------------------------------------------------
# STREAM PROXY (Added Program support)
# ----------------------------------------------------------------------
@app.route('/proxy_stream/<item_id>/<mode>/<item_type>')
def proxy_stream(item_id, mode, item_type):
    if 'user_id' not in session:
        return "Unauthorized", 401

    # 🔥 Support Program (Live TV)
    is_audio = 'audio' in item_type.lower()
    if is_audio:
        endpoint = f"/Audio/{item_id}/stream"
    elif item_type.lower() == 'program':
        endpoint = f"/LiveTv/Channels/{item_id}/MediaStream"  # Live TV Program
    else:
        endpoint = f"/Videos/{item_id}/stream"

    if mode == "direct":
        params = {"Static": "true"}
    else:
        if is_audio:
            params = {"Container": "mp3", "AudioCodec": "mp3", "EnableAutoStreamCopy": "false"}
        else:
            params = {
                "Container": "mp4", 
                "VideoCodec": "h264", 
                "AudioCodec": "aac",
                "EnableAutoStreamCopy": "false"
            }

    auth = (
        f'MediaBrowser Client="Basic Jellyfin Client", Device="Flask Client", '
        f'DeviceId="{DEVICE_ID}", Version="1.0", Token="{session["access_token"]}"'
    )
    headers = {'X-Emby-Authorization': auth}
    stream_url = f"{JELLYFIN_SERVER}{endpoint}"

    try:
        r = requests.get(stream_url, headers=headers, params=params,
                         stream=True, verify=False, timeout=30)
        r.raise_for_status()
        return Response(r.iter_content(chunk_size=1024),
                        content_type=r.headers.get('Content-Type', 'application/octet-stream'))
    except requests.RequestException as e:
        return f"Streaming error: {str(e)}", 500


# ----------------------------------------------------------------------
# PLAYER PAGE
# ----------------------------------------------------------------------
@app.route('/play/<item_id>/<item_type>')
def play(item_id, item_type):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    direct_url = url_for('proxy_stream', item_id=item_id, mode='direct',
                         item_type=item_type, _external=True)
    transcode_url = url_for('proxy_stream', item_id=item_id, mode='transcode',
                            item_type=item_type, _external=True)

    return render_template('player.html',
                           direct_url=direct_url,
                           transcode_url=transcode_url,
                           item_type=item_type)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9097, debug=True)
