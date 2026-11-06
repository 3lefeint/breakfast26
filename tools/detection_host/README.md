# The dart detection on the board host

Autodarts and the dart detection of Breakfast both need the three board cameras, and only one program can hold them. These files make the
choice a service switch.

| file | goes to | what it does |
|------|---------|--------------|
| `breakfast-detect-host.sh` | `/usr/local/bin/` | finds the cameras by USB port and creates the stack (`start`), takes it down (`stop`) |
| `breakfast-detect.service` | `/etc/systemd/system/` | the stack as a service; `Conflicts=autodarts.service` makes starting one stop the other |
| `50-breakfast-detect.rules` | `/etc/polkit-1/rules.d/` | the board host user may start and stop these two units without a password |

Install (as root, once):

    install -m 755 breakfast-detect-host.sh /usr/local/bin/
    install -m 644 breakfast-detect.service /etc/systemd/system/
    sed 's/BOARD_USER/<user of the board host>/' 50-breakfast-detect.rules > /etc/polkit-1/rules.d/50-breakfast-detect.rules
    printf 'DETECT_DIR=/path/to/the/folder/with/docker-compose.detection.yml\nCAM_PATHS="<name> <name> <name>"\n' > /etc/default/breakfast-detect
    systemctl daemon-reload

`CAM_PATHS` are the names of the three capture nodes of this board under `/dev/v4l/by-path` (the ones that end in `video-index0`), in the
order of the cameras; there is no default, they depend on the USB ports the cameras are plugged into.

Use:

    systemctl start breakfast-detect      # the detection takes the cameras (Autodarts is stopped)
    systemctl start autodarts             # back to Autodarts (the detection is taken down): the fall-back
    systemctl disable autodarts && systemctl enable breakfast-detect      # the detection after a boot

`tools/detection_deploy.sh host-files` copies these files to the board host (it installs nothing). The fall-back is a command on the host: the
container of Breakfast cannot reach systemd, so who switches is whoever has a shell there (with the polkit rule: the board host user, no password).

## In the installed Breakfast (no separate stack)

The stack above is a test stack with its own data. For the Breakfast that is installed on the board host (the checkout with
`docker-compose.yml`) the detection is a setting of that Breakfast:

| file | goes to | what it does |
|------|---------|--------------|
| `docker-compose.override.yml` | next to `docker-compose.yml` of the checkout | builds the image with the detection and maps the cameras (`/dev/autodarts-cam0` to `2`, the links of the udev rule Autodarts needs, so the numbers of `/dev/videoN` do not matter), the group `video` and the USB bus (a Stream Deck on the host) |
| `breakfast-mode.sh` | `/usr/local/bin/` | `own`: stop Autodarts, `[cameras] enabled = true`, restart Breakfast; `autodarts`: the other way round; `status` |

Switch (as the host user, with the polkit rule above; refuses while a match is running, `--force` overrides):

    breakfast-mode.sh own
    breakfast-mode.sh autodarts

The stats.db and the rest of the config stay as they are, only `enabled` of `[cameras]` changes (the section is added the first time). Rollout steps:
copy the two files, build the image with the code of this branch (`docker compose up -d --build`), then `breakfast-mode.sh own`.
