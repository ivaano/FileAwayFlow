﻿## File Away Flow
File Away Flow is an API that allows you to move files between folders, it is helpful for postprocessing files.

Consider the following scenario:
![diagram.png](diagram.png)

If we want to move files after they are downloaded from (`/share/docker_volumes/sabnzbd/downloads`) to (`/share/nas/isos`), 
we can use a postprocess script, but it will execute in the container (Sabnzbd) and not in the host machine,
so we will need to mount the (`/share/nas/isos`)  as part of the container which will require to create a new 
mountpoint inside the container and modify the Dockerfile. or we can use this API that runs on the host machine, and the postprocess script
simply calls this API to do the moving.

## Installation

This project consists of two parts, the API and the postprocess script. 

to build the API you need to install rust and cargo (https://www.rust-lang.org/tools/install).
```bash
cargo build --color=always --profile release --package FileAwayFlow --bin FileAwayFlow
  Finished `release` profile [optimized] target(s) in 2.02s
```
The binary should be in the `target/release` directory, copy the binary file to `/usr/local/bin/fileawayflow`

Create a system service to start the API on boot:
```bash
create a systemd service in debian you can put it on `/etc/systemd/system/fileaway.service`
```

```ini
[Unit]
Description=API to move files around.
After=syslog.target network.target

[Service]
User=ivan
Group=ivan
UMask=0002
Type=simple
Environment="API_KEY=secret"
ExecStart=/usr/local/bin/fileawayflow 8002
TimeoutStopSec=10
KillMode=process
Restart=on-failure


[Install]
WantedBy=multi-user.target
```

To start the service on boot:
```bash
sudo systemctl daemon-reload
sudo systemctl enable fileaway.service
sudo systemctl start fileaway 
sudo systemctl status fileaway
● fileaway.service - API to move files around
     Loaded: loaded (/etc/systemd/system/fileaway.service; enabled; preset: enabled)
     Active: active (running) since Wed 2024-10-23 15:06:11 PDT; 2s ago
   Main PID: 647632 (fileawayflow)
      Tasks: 7 (limit: 9357)
     Memory: 1.1M
        CPU: 4ms
     CGroup: /system.slice/fileaway.service
             └─647632 /usr/local/bin/fileawayflow 8002

Oct 23 15:06:11 zenyata systemd[1]: Started fileaway.service - API to move files around.
Oct 23 15:06:11 zenyata fileawayflow[647632]: 🚀 Server started successfully, listening on port 8002
```


## Environment Variables
`API_KEY` is the API key that will be used for authentication, if is not set, it will default to `123456`

## Program Arguments
The server only takes 1 argument which is the port number. The default port is `8000`

The second part involves the postprocessing script that will run once the download is complete, there is a 
sample script for sabnzbd, that will call this API passing the file to move, the mapping of the paths is on 
that script, for other downloaders you can change the script to call this API.