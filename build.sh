#!/bin/bash
pip install -r requirements.txt
python -c "import imageio; imageio.plugins.ffmpeg.download()"
