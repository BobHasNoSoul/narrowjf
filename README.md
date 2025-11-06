# narrowjf
A thin.. very thin.. webclient designed for potato clients like some old first gen smart tvs.. simply run this in a server and add it to a subdomain and then connect the potato client to it.. mininal loading easy to use.


this is created to fix a use case for my sisters tv.. it was an older pos that needed a client that could run without crashing the browser on it.. there was no app store so i made this to fix the issue 

put the files on your linux server (or windows and just run the python script) and run the bash script background.sh to background it for you on linux.


IMPORTANT NOTE: 

you need to change the server lan ip in the app.py and the SUPERSECRETKEY because they are important.. just generate a random key to use and use that.

this is rough around the edges but works and can be used on most potatos.. next step when free is to add live tv support and collections support.
