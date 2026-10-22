"""Player names are stored in lower case and shown in upper case by the interface.

`normalize` is the one place that decides how a name is stored; everything that lets a name in (the REST
bodies, MQTT commands, the names of the board service, the player registry) goes through it. The voice caller
looks a name up in lower case, so a stored name is also the key of its voice file.
"""


def normalize(name):
    """The stored form of a player name: stripped, in lower case. Anything but a string is returned as it is."""
    return name.strip().lower() if isinstance(name, str) else name


def normalize_all(names):
    return [normalize(n) for n in names]


def normalize_command(cmd: dict) -> dict:
    """The names in an MQTT command (`players`, `player`, `name`), in place."""
    if isinstance(cmd.get("players"), list):
        cmd["players"] = normalize_all(cmd["players"])
    for key in ("player", "name"):
        if isinstance(cmd.get(key), str):
            cmd[key] = normalize(cmd[key])
    return cmd
