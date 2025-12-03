# 🎓 DYFH — Do Your F******* Homework
A privacy-first, local-only study & task tracker.

DYFH is a lightweight desktop app for managing coursework, tracking study time, and keeping your academic life in order — without relying on the cloud, accounts, or outside services. Everything runs locally and is completely under your control.

The app is written in Python + CustomTkinter, includes dark-mode analytics, and can be compiled into a standalone Windows .exe with PyInstaller.
There are two options for using it:
1. [Run it with Python each time]("#-running-dyfh-from-source-files")
2. [Build a .exe file]("#-build-the-windows-exe-file")

## ✨ Features
### 📝 Task Management
- Add, edit, and delete tasks
- Optional due dates with auto-highlighting for overdue items
- Class tags and quick class filtering
- Inline URLs (open directly from the task card)
- KPI-style summary badges showing cumulative study time per class

### ⏱ Time Tracking
- One-click Start/Stop timers for any task
- Automatically logs sessions with timestamps

### 📊 Analytics (COMING SOON!)
- Line/area chart: Cumulative time by day
- Sorted bar chart: Top tasks by total minutes
- Weekly bar chart: Time spent by weekday
- Class selector lets you visualize specific classes

### 🗂 Course Organization & Archiving
- Archive old classes without deleting their data
- Toggle archived classes in and out of the UI
- Everything remains available for analytics

### 🔗 Zoom Links That Live Inside Class Badges
- KPI badges act as instant Zoom launchers
- No separate button clutter
- Easy to manage in Settings

### ⚙️ Customizable Settings
- Manage Zoom links
- Archive / unarchive classes
- Delete completed tasks

### 💾 100% Local Storage

DYFH stores everything in simple JSON files:
```
tasks.json
zoom_links.json
settings.json
```
## Screenshot
![application screenshot showing to do list](https://github.com/rlbergh/DYFH-DoYourF-Homework/blob/main/DYFH-UI.png)

## 🚀 Running DYFH from source files

1. Install Python
  - Download Python 3.10+ from:
  - https://www.python.org/downloads/
  - Be sure to check: Add Python to PATH

2. Download this Repo
  - GitHub → Code → Download ZIP
  - Unzip and open the folder.

3. Create a virtual environment in that folder:
```
cd "[directory folder path where you unzipped repo contents]"
python -m venv .venv
```
and activate it:
```
.\.venv\Scripts\activate
```
4. Install dependencies (matplotlib here for future feature)
```
pip install customtkinter matplotlib
```
5. Run the app
```
python to_done.py
```

OR

## 🏗 Build the Windows .exe file
DYFH can be compiled into a fully self-contained Windows application using PyInstaller. This is how I use it. I then have it open on my desktop all the time while I'm working and created a shortcut to the application on my taskbar.
1. Follow steps 1-4 from "Running DYFH from source files" 
2. Install PyInstaller
```
pip install pyinstaller
```
3. Run the build command, ensuring your virtual environment is activated
```
.\.venv\Scripts\pyinstaller.exe --noconsole --name=DYFH --icon=DYFH-icon.ico --add-data=tasks.json:. --add-data=zoom_links.json:. --add-data=settings.json:. --hidden-import=customtkinter to_done.py
```
4. The built exe file appears in:
```
dist/DYFH/DYFH.exe
```
5. Double click the .exe to start
6. Happy homework tracking!

## [Change log](https://github.com/rlbergh/DYFH-DoYourF-Homework/blob/main/change_log.md)



