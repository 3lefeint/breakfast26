Breakfast for Windows
=====================

Start:      double-click breakfast.exe (a console window opens, closing it stops Breakfast).
First run:  your browser opens the Settings page. Enter your Autodarts account under
            "Autodarts Source", save, and press Restart.
Web UI:     http://localhost:8080   (TV view: /tv, sound: /audio on the device with the speakers)
            Windows asks once whether Breakfast may use the network: allow it for private
            networks, so a TV or phone can reach it.

Your files: everything you create lives in the "data" folder next to breakfast.exe
            (config.toml, stats.db, sounds). An update never touches it. Back it up to keep
            your statistics.

Autostart:  right-click install-autostart.ps1 and choose "Run with PowerShell" to start Breakfast
            when you log in. remove-autostart.ps1 undoes it.

Updates:    Settings -> Updates checks GitHub for a newer release and installs it. The old
            version is kept until the new one answers, and comes back if it does not.

Unsigned program: Windows may show "Windows protected your PC". Click "More info", then
            "Run anyway". The download page has a SHA-256 file to check the zip.

More:       https://github.com/3lefeint/breakfast26
