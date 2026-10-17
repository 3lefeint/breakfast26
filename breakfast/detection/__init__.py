"""Own dart detection from the board cameras (replaces the board manager of Autodarts as the board source).

geometry     the board model: pixel to board millimetres per camera, ring radii, the field at a point
detector     one dart: the tip in the difference image of every camera, fused to a field
tracker      the state of the board over time: a dart has landed, the darts were taken out
cameras      reading the USB cameras (V4L2) and replaying frames for tests
calibration  the automatic fit of the board model on the empty board
source       the board source of Breakfast: a worker process that sends the same state messages as the board manager
"""
