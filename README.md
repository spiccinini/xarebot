# Xarebot

Xarebot can send and receive XMPP text and media from the cmdline.
I use it mainly to exchange things with myself from my smartphone to the cmdline and vice versa. 
I run a snikket chat instance but any XMPP server should work.
This bot does not need to be running to receive messages, it fetches them using the archive feature of the server.

Features

* Sends OMEMO-encrypted text messages
* Sends OMEMO-encrypted files
* Reads unencrypted messages from the server archive (recent messages)
* Downloads unencrypted files from the archive

Receiving OMEMO-encrypted messages is partially implemented. 
The client must be active at the moment of message arrival to decrypt OMEMO content. 
Reading encrypted messages from MAM is yet to be done.

## Examples

### Sends a text message and also prints the last messages received
`uv run xarebot.py --send-msg 'Greetings from Pycamp 2025!'`

### Sends a file and also prints the last messages received
`uv run xarebot.py --send-file ~/Downloads/foo.jpeg`

### Just receives and prints the last messages received
`uv run xarebot.py`

## Usage

Copy credentials_example.py to credentials.py.

## History

I started working on this idea in Argentina's awesome PyCamp 2025.

## License

It is AGPL lincensed. Please read all the licenses of the dependencies.

## TODO

* Expose it as a QubesOs service so the bot only runs when requests and 
in one qube but every qube can send or receive messages and files.
* Make the encription reception work.