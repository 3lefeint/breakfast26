"""Which video devices the board cameras are. On the Linux board host the udev rule of `tools/detection_host/install.sh` puts one node per
camera into `VIDEO_DIR`, named after its USB port without the bus number (`1.1.1`); `[cameras] ports` in config.toml names the three
cameras, in the order of the board, by that port. Without `ports` the list `devices` is used, without that `DEFAULT_DEVICES`."""
import os
import re

VIDEO_DIR = "/dev/breakfast-video"
DEFAULT_DEVICES = ["/dev/cam0", "/dev/cam1", "/dev/cam2"]     # the names the compose files of older installations give the cameras in the container
PORT_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


def valid_ports(ports):
    """True for three different USB ports like `1.1.1`."""
    return isinstance(ports, list) and len(ports) == 3 and all(isinstance(p, str) and PORT_RE.match(p) for p in ports) and len(set(ports)) == 3


def found():
    """The USB ports of the cameras that are plugged in (the nodes of `VIDEO_DIR`), sorted."""
    try:
        return sorted(n for n in os.listdir(VIDEO_DIR) if PORT_RE.match(n))
    except OSError:
        return []


def path_of(port):
    return os.path.join(VIDEO_DIR, port)


def device_paths(cfg):
    """The devices of the three cameras for the `[cameras]` section `cfg`: by `ports`, else `devices`, else the default names."""
    ports = cfg.get("ports")
    if valid_ports(ports):
        return [path_of(p) for p in ports]
    return cfg.get("devices") or DEFAULT_DEVICES


def snapshot(path, width=800, height=600):
    """One JPEG picture of the camera at `path`, None when it cannot be opened (missing, or held by another program)."""
    import cv2
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        for _ in range(5):                    # the first pictures of a camera that was just opened are dark
            ok, frame = cap.read()
        if not ok or frame is None:
            return None
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return jpg.tobytes() if ok else None
    finally:
        cap.release()
