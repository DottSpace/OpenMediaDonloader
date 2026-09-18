# OpenMediaDownloader 🎬📥

**OpenMediaDownloader** is a modern, feature-rich graphical user interface (GUI) application built with **PyQt6** and powered by **yt-dlp**. It provides a seamless, robust, and asynchronous media downloading experience with automatic dependency management.

---

## ✨ Features

- **Asynchronous UI Architecture:** Keeps the interface fully responsive during heavy metadata analysis and download tasks using dedicated worker threads (`QThread`).
- **Auto FFmpeg Setup:** Automatically checks, downloads, and configures the required `ffmpeg` binaries on startup if not already present in the environment.
- **Advanced Metadata Analysis:** Fetches video information, available resolutions, video duration, and supported subtitle tracks prior to download.
- **Flexible Export Formats:** 
  - Video streams (Native container, MP4, MKV, WebM)
  - Audio extraction (`MP3` or `M4A` at 320 kbps)
  - Custom resolution filtering (from highest auto-quality down to specific pixel heights)
- **Subtitle Integration:** Option to download standard or auto-generated/translated subtitles in a wide variety of selectable languages.
- **Robust Cancellation & Cleanup:** Safely abort ongoing operations at any moment while automatically purging partial/zombie temporary files.
- **Modern Dark-Themed UI:** Sleek, professional custom stylesheet designed for optimal usability.

---

## 🚀 Installation & Requirements

Make sure you have **Python 3.8+** installed on your system.

1. Clone or download this repository.
2. Install the required Python packages:
   ```bash
   pip install PyQt6 yt-dlp
   ```
3. Run the application:
   ```bash
   python OpenMediaDownloader.py
   ```

---

## 🛠️ Usage

1. Launch the application. Wait a brief moment for the automated FFmpeg environment check to complete.
2. Paste your target media URL into the **Target URL** field.
3. Click **Fetch Metadata** to inspect available resolutions, formats, and subtitles.
4. Choose your preferred export configuration (resolution, container, format, or audio extraction).
5. Select an output destination directory using the **Browse** button.
6. Click **Download** to start the pipeline and track live progress!
