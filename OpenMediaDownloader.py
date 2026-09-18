import os
import re
import sys
import urllib.request
import zipfile
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, 
    QLineEdit, QPushButton, QTextEdit, QVBoxLayout, 
    QHBoxLayout, QFileDialog, QComboBox, QGroupBox, QGridLayout,
    QCheckBox, QProgressBar
)
import yt_dlp

# --- WORKER FOR FFMPEG AUTO-SETUP ---
class FFMpegSetupWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self):
        super().__init__()

    def run(self):
        data_dir = os.path.join(os.getcwd(), "data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        
        ffmpeg_path = os.path.join(data_dir, "ffmpeg.exe")
        
        if not os.path.exists(ffmpeg_path):
            self.log.emit("[*] FFmpeg not found in data directory. Downloading automatically (please wait)...")
            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            zip_path = os.path.join(data_dir, "ffmpeg_temp.zip")
            
            try:
                urllib.request.urlretrieve(url, zip_path)
                self.log.emit("[*] Download complete. Extracting binary...")
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    for member in zf.namelist():
                        if member.endswith("bin/ffmpeg.exe"):
                            filename = os.path.basename(member)
                            source = zf.open(member)
                            target_path = os.path.join(data_dir, filename)
                            with open(target_path, "wb") as target:
                                target.write(source.read())
                            break
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                self.log.emit("[+] FFmpeg successfully installed and ready!")
            except Exception as e:
                self.log.emit(f"[!] Critical error during automated FFmpeg download: {e}")
        else:
            self.log.emit("[+] FFmpeg dependency verified successfully.")
            
        self.finished.emit(ffmpeg_path)

# --- WORKER FOR METADATA ANALYSIS ---
class VideoAnalyzerWorker(QObject):
    finished = pyqtSignal(dict)
    log = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        ydl_opts = {'extract_flat': False, 'skip_download': True, 'noplaylist': True}
        try:
            self.log.emit("[*] Fetching video metadata...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if self._is_cancelled:
                    return
                info = ydl.extract_info(self.url, download=False)
                if not self._is_cancelled:
                    self.finished.emit(info)
        except Exception as e:
            if not self._is_cancelled:
                self.log.emit(f"[!] Error during metadata extraction: {str(e)}")
                self.finished.emit({})

# --- WORKER FOR MEDIA DOWNLOAD ---
class VideoDownloaderWorker(QObject):
    progress = pyqtSignal(int, str, str) # percent, speed, eta
    log = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, url, ydl_opts):
        super().__init__()
        self.url = url
        self.ydl_opts = ydl_opts
        self._is_cancelled = False
        self.tracked_files = set()

    def cancel(self):
        self._is_cancelled = True
        for filepath in list(self.tracked_files):
            extensions_to_check = [filepath, filepath + ".part", filepath + ".ytdl", filepath + ".webm", filepath + ".mp4"]
            for candidate in extensions_to_check:
                if os.path.exists(candidate):
                    try:
                        os.remove(candidate)
                        self.log.emit(f"[*] Purged zombie file: {os.path.basename(candidate)}")
                    except Exception:
                        pass

    def run(self):
        def clean_ansi(text):
            return re.sub(r'\x1b\[[0-9;]*m', '', str(text))

        def logger_hook(d):
            if self._is_cancelled:
                raise Exception("Operation aborted by user.")
            
            if 'filename' in d:
                self.tracked_files.add(d['filename'])
            if 'tmpfilename' in d:
                self.tracked_files.add(d['tmpfilename'])
            
            if d['status'] == 'downloading':
                p_str = clean_ansi(d.get('_percent_str', '0%')).replace('%', '').strip()
                try:
                    percent = int(float(p_str))
                except ValueError:
                    percent = 0
                
                speed = clean_ansi(d.get('_speed_str', 'N/A'))
                eta = clean_ansi(d.get('_eta_str', 'N/A'))
                
                self.progress.emit(percent, speed, eta)
                
            elif d['status'] == 'finished':
                self.log.emit("[*] Finalizing media container (muxing)...")
                if 'filename' in d:
                    self.tracked_files.add(d['filename'])

        self.ydl_opts['progress_hooks'] = [logger_hook]

        try:
            self.log.emit("[*] Starting download pipeline...")
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                ydl.download([self.url])
            if not self._is_cancelled:
                self.log.emit("[+] Download completed successfully.")
                self.finished.emit(True)
        except Exception as e:
            if self._is_cancelled:
                self.log.emit("[!] Download cancelled and partial files purged.")
            else:
                self.log.emit(f"[!] Critical Error: {str(e)}")
            self.finished.emit(False)

# --- MAIN APPLICATION WINDOW ---
class YouTubeDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Open Media Downloader")
        self.resize(780, 850)
        
        self.output_path = os.getcwd()
        self.available_resolutions = []
        self.available_subtitles = []
        
        self.analysis_thread = None
        self.analysis_worker = None
        self.download_thread = None
        self.download_worker = None
        
        self.init_ui()
        self.apply_stylesheet()
        
        # Trigger background check/download for FFmpeg after UI renders
        self.init_ffmpeg_check()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 1. Source and Destination Section
        source_group = QGroupBox("1. Source & Destination")
        source_layout = QGridLayout(source_group)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste target media URL here...")
        self.analyze_btn = QPushButton("Fetch Metadata")
        self.analyze_btn.setEnabled(False) # Locked until FFmpeg check completes
        self.analyze_btn.clicked.connect(self.start_analysis)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.select_output_dir)
        self.path_label = QLabel(f"Destination: {self.output_path}")

        source_layout.addWidget(QLabel("Target URL:"), 0, 0)
        source_layout.addWidget(self.url_input, 0, 1)
        source_layout.addWidget(self.analyze_btn, 0, 2)
        source_layout.addWidget(QLabel("Folder:"), 1, 0)
        source_layout.addWidget(self.path_label, 1, 1)
        source_layout.addWidget(self.browse_btn, 1, 2)
        
        main_layout.addWidget(source_group)

        # Video Info Section
        self.info_label = QLabel("Initializing application environment...")
        self.info_label.setStyleSheet("color: #a0a0a0; font-style: italic;")
        main_layout.addWidget(self.info_label)

        # 2. Export Configuration Section
        config_group = QGroupBox("2. Download Configuration")
        config_layout = QGridLayout(config_group)

        self.download_video_checkbox = QCheckBox("Download Video Stream")
        self.download_video_checkbox.setChecked(True)
        self.download_video_checkbox.setStyleSheet("font-weight: bold; font-size: 13px; color: #2ecc71;")

        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Highest Quality Available (Auto)", "best")
        self.quality_combo.setEnabled(False)

        self.format_combo = QComboBox()
        self.format_combo.addItem("Native Container (Best Quality / WebM)", "native")
        self.format_combo.addItem("MP4", "mp4")
        self.format_combo.addItem("MKV", "mkv")
        self.format_combo.addItem("WebM", "webm")
        self.format_combo.addItem("MP3 (Audio Extract)", "mp3")
        self.format_combo.addItem("M4A (Audio Extract)", "m4a")

        config_layout.addWidget(self.download_video_checkbox, 0, 0, 1, 2)
        config_layout.addWidget(QLabel("Resolution:"), 1, 0)
        config_layout.addWidget(self.quality_combo, 1, 1)
        config_layout.addWidget(QLabel("Container / Format:"), 2, 0)
        config_layout.addWidget(self.format_combo, 2, 1)

        main_layout.addWidget(config_group)

        # 3. Subtitles Section
        sub_group = QGroupBox("3. Subtitle Options")
        sub_layout = QGridLayout(sub_group)

        self.download_sub_checkbox = QCheckBox("Download Subtitles")
        self.download_sub_checkbox.setChecked(False)
        self.download_sub_checkbox.setStyleSheet("font-weight: bold; font-size: 13px; color: #3498db;")
        self.download_sub_checkbox.toggled.connect(self.toggle_subtitles_options)

        self.sub_warning_label = QLabel("⚠️ Notice: Auto-generated or translated subtitles might include semantic errors.")
        self.sub_warning_label.setStyleSheet("color: #e74c3c; font-size: 11px; font-style: italic;")

        self.sub_lang_combo = QComboBox()
        self.sub_lang_combo.setEnabled(False)

        sub_layout.addWidget(self.download_sub_checkbox, 0, 0, 1, 2)
        sub_layout.addWidget(self.sub_warning_label, 1, 0, 1, 2)
        sub_layout.addWidget(QLabel("Language:"), 2, 0)
        sub_layout.addWidget(self.sub_lang_combo, 2, 1)

        main_layout.addWidget(sub_group)

        # Progress Bar & Control Action Buttons
        control_layout = QVBoxLayout()
        control_layout.setSpacing(6)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setVisible(False)
        control_layout.addWidget(self.progress_bar)

        self.progress_status_label = QLabel("")
        self.progress_status_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        self.progress_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_status_label.setVisible(False)
        control_layout.addWidget(self.progress_status_label)

        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        self.download_btn.setObjectName("DownloadButton")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.start_download)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("CancelButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_operation)

        btn_layout.addWidget(self.download_btn)
        btn_layout.addWidget(self.cancel_btn)
        control_layout.addLayout(btn_layout)

        main_layout.addLayout(control_layout)

        # Log Console Area
        log_group = QGroupBox("System Console Logs")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        main_layout.addWidget(log_group)

    def apply_stylesheet(self):
        stylesheet = """
            QMainWindow { background-color: #181818; color: #ffffff; font-family: 'Segoe UI', sans-serif; }
            QGroupBox { border: 1px solid #3d3d3d; border-radius: 6px; margin-top: 12px; font-weight: bold; color: #3498db; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QLabel, QCheckBox { color: #dcdcdc; }
            QLineEdit, QComboBox { background-color: #262626; border: 1px solid #4a4a4a; border-radius: 4px; padding: 6px; color: #ffffff; }
            QPushButton { background-color: #2c2c2c; border: 1px solid #4a4a4a; border-radius: 4px; padding: 6px 14px; color: #ffffff; font-weight: 600; }
            QPushButton:hover { background-color: #383838; border-color: #5a5a5a; }
            QPushButton:disabled { background-color: #202020; color: #555555; border: 1px solid #2a2a2a; }
            QPushButton#DownloadButton { background-color: #2196F3; border: none; font-size: 13px; padding: 10px; border-radius: 5px; color: white; }
            QPushButton#DownloadButton:hover { background-color: #1976D2; }
            QPushButton#CancelButton { background-color: #d32f2f; border: none; font-size: 13px; padding: 10px; border-radius: 5px; color: white; }
            QPushButton#CancelButton:hover { background-color: #c62828; }
            QProgressBar { border: 1px solid #4a4a4a; border-radius: 4px; text-align: center; color: white; background: #202020; font-weight: bold; }
            QProgressBar::chunk { background-color: #2196F3; border-radius: 3px; }
            QTextEdit { background-color: #121212; border: 1px solid #2c2c2c; color: #00e676; font-family: Consolas, monospace; font-size: 11px; border-radius: 4px; }
        """
        self.setStyleSheet(stylesheet)

    def init_ffmpeg_check(self):
        self.append_log("[*] Checking system dependencies...")
        self.ffmpeg_thread = QThread()
        self.ffmpeg_worker = FFMpegSetupWorker()
        self.ffmpeg_worker.moveToThread(self.ffmpeg_thread)
        
        self.ffmpeg_thread.started.connect(self.ffmpeg_worker.run)
        self.ffmpeg_worker.log.connect(self.append_log)
        self.ffmpeg_worker.finished.connect(self.on_ffmpeg_ready)
        
        self.ffmpeg_thread.start()

    def on_ffmpeg_ready(self, path):
        self.ffmpeg_thread.quit()
        self.ffmpeg_thread.wait()
        self.analyze_btn.setEnabled(True)
        self.info_label.setText("No metadata fetched yet. Provide a link and click 'Fetch Metadata'.")
        self.info_label.setStyleSheet("color: #a0a0a0; font-style: italic;")

    def toggle_subtitles_options(self, checked):
        if checked and self.available_subtitles:
            self.sub_lang_combo.setEnabled(True)
        else:
            self.sub_lang_combo.setEnabled(False)

    def select_output_dir(self):
        dir_name = QFileDialog.getExistingDirectory(self, "Select Destination Directory")
        if dir_name:
            self.output_path = dir_name
            self.path_label.setText(f"Destination: {self.output_path}")

    def append_log(self, text):
        self.log_output.append(text)

    # --- METADATA ANALYSIS FLOW ---
    def start_analysis(self):
        url = self.url_input.text().strip()
        if not url:
            self.append_log("[!] Error: Please provide a valid URL string.")
            return
        
        self.analyze_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.info_label.setText("Analyzing target media... Please wait.")
        
        self.analysis_thread = QThread()
        self.analysis_worker = VideoAnalyzerWorker(url)
        self.analysis_worker.moveToThread(self.analysis_thread)
        
        self.analysis_thread.started.connect(self.analysis_worker.run)
        self.analysis_worker.finished.connect(self.on_analysis_finished)
        self.analysis_worker.log.connect(self.append_log)
        
        self.analysis_thread.start()

    def on_analysis_finished(self, info):
        self.analysis_thread.quit()
        self.analysis_thread.wait()
        
        self.analyze_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        if not info:
            self.info_label.setText("Failed to retrieve media information.")
            return

        title = info.get('title', 'Unknown Title')
        duration = info.get('duration_string', 'N/A')
        formats = info.get('formats', [])

        resolutions = set()
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('height'):
                resolutions.add(f['height'])

        self.available_resolutions = sorted(list(resolutions), reverse=True)
        max_quality_str = f"{self.available_resolutions[0]}p" if self.available_resolutions else "N/A"

        self.info_label.setText(
            f"<b>Title:</b> {title} | <b>Duration:</b> {duration} | <span style='color: #2ecc71;'><b>Max Resolution:</b> {max_quality_str}</span>"
        )

        self.quality_combo.clear()
        self.quality_combo.addItem("Highest Quality Available (Auto)", "best")
        
        if self.available_resolutions:
            highest = self.available_resolutions[0]
            lowest = self.available_resolutions[-1]
            medium = self.available_resolutions[len(self.available_resolutions) // 2]

            self.quality_combo.addItem(f"Highest ({highest}p)", str(highest))
            if medium != highest and medium != lowest:
                self.quality_combo.addItem(f"Medium ({medium}p)", str(medium))
            if lowest != highest:
                self.quality_combo.addItem(f"Lowest ({lowest}p)", str(lowest))

            self.quality_combo.insertSeparator(self.quality_combo.count())
            for res in self.available_resolutions:
                self.quality_combo.addItem(f"{res}p", str(res))

        self.quality_combo.setEnabled(True)

        language_names = {
            "af": "Afrikaans", "sq": "Albanian", "am": "Amharic", "ar": "Arabic",
            "hy": "Armenian", "az": "Azerbaijani", "eu": "Basque", "be": "Belarusian",
            "bn": "Bengali", "bs": "Bosnian", "bg": "Bulgarian", "ca": "Catalan",
            "zh-Hans": "Chinese (Simplified)", "zh-Hant": "Chinese (Traditional)", "cs": "Czech", 
            "da": "Danish", "nl": "Dutch", "en": "English", "et": "Estonian",
            "fil": "Filipino", "fi": "Finnish", "fr": "French", "gl": "Galician", 
            "ka": "Georgian", "de": "German", "el": "Greek", "gu": "Gujarati", 
            "ht": "Haitian Creole", "iw": "Hebrew", "hi": "Hindi", "hu": "Hungarian", 
            "is": "Icelandic", "id": "Indonesian", "ga": "Irish", "it": "Italian", 
            "ja": "Japanese", "jv": "Javanese", "kn": "Kannada", "kk": "Kazakh", 
            "km": "Khmer", "ko": "Korean", "ky": "Kyrgyz", "lo": "Lao", 
            "la": "Latin", "lv": "Latvian", "lt": "Lithuanian", "lb": "Luxembourgish", 
            "mk": "Macedonian", "mg": "Malagasy", "ms": "Malay", "ml": "Malayalam", 
            "mt": "Maltese", "mi": "Maori", "mr": "Marathi", "mn": "Mongolian", 
            "ne": "Nepali", "no": "Norwegian", "fa": "Persian", "pl": "Polish", 
            "pt": "Portuguese", "pa": "Punjabi", "ro": "Romanian", "ru": "Russian", 
            "sr": "Serbian", "sk": "Slovak", "sl": "Slovenian", "so": "Somali", 
            "es": "Spanish", "su": "Sundanese", "sw": "Swahili", "sv": "Swedish", 
            "tg": "Tajik", "ta": "Tamil", "te": "Telugu", "th": "Thai", 
            "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek", 
            "vi": "Vietnamese", "cy": "Welsh", "yi": "Yiddish", "yo": "Yoruba", 
            "zu": "Zulu"
        }

        subtitles_found = set()
        for lang in list(info.get('subtitles', {}).keys()) + list(info.get('automatic_captions', {}).keys()):
            if lang in language_names:
                subtitles_found.add(lang)

        self.available_subtitles = list(subtitles_found)

        self.sub_lang_combo.clear()
        if self.available_subtitles:
            sorted_subs = sorted(self.available_subtitles, key=lambda code: language_names[code])
            for code in sorted_subs:
                self.sub_lang_combo.addItem(language_names[code], code)
            
            en_index = self.sub_lang_combo.findData("en")
            if en_index != -1:
                self.sub_lang_combo.setCurrentIndex(en_index)
            
            self.append_log(f"[+] Metadata fetched successfully. Max Quality: {max_quality_str}. Resolutions found: {len(self.available_resolutions)}. Subtitles: {len(self.available_subtitles)} languages.")
        else:
            self.sub_lang_combo.addItem("No subtitles available", "")
            self.append_log(f"[+] Metadata fetched successfully. Max Quality: {max_quality_str}. Resolutions found: {len(self.available_resolutions)}. Subtitles: None.")

        self.toggle_subtitles_options(self.download_sub_checkbox.isChecked())
        self.download_btn.setEnabled(True)

    # --- DOWNLOAD FLOW ---
    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            return
        
        self.download_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_status_label.setText("Initializing download...")
        self.progress_status_label.setVisible(True)
        
        selected_res_data = self.quality_combo.currentData()
        download_video = self.download_video_checkbox.isChecked()
        download_subs = self.download_sub_checkbox.isChecked()
        sub_lang = self.sub_lang_combo.currentData() if download_subs and self.available_subtitles else None
        selected_format = self.format_combo.currentData()

        ffmpeg_bin_dir = os.path.join(os.getcwd(), "data")

        ydl_opts = {
            'outtmpl': f'{self.output_path}/%(title)s.%(ext)s',
            'noplaylist': True,
            'ffmpeg_location': ffmpeg_bin_dir,
        }

        if not download_video:
            ydl_opts['skip_download'] = True
            self.append_log("[*] Video stream download disabled.")

        if download_subs and sub_lang:
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitlesformat'] = 'srt'
            ydl_opts['subtitleslangs'] = [sub_lang]
            self.append_log(f"[*] Subtitles enabled for language code: {sub_lang}")

        if download_video:
            if selected_res_data == "best":
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
            else:
                ydl_opts['format'] = f'bestvideo[height<={selected_res_data}]+bestaudio/best[height<={selected_res_data}]'

            if selected_format == "mp3":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }]
            elif selected_format == "m4a":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                    'preferredquality': '320',
                }]
            elif selected_format == "native":
                self.append_log("[*] Using YouTube native format container.")
            elif selected_format in ["mp4", "mkv", "webm"]:
                ydl_opts['merge_output_format'] = selected_format

        self.download_thread = QThread()
        self.download_worker = VideoDownloaderWorker(url, ydl_opts)
        self.download_worker.moveToThread(self.download_thread)

        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.progress.connect(self.update_progress)
        self.download_worker.log.connect(self.append_log)
        self.download_worker.finished.connect(self.on_download_finished)

        self.download_thread.start()

    def update_progress(self, percent, speed, eta):
        self.progress_bar.setValue(percent)
        self.progress_status_label.setText(f"Speed: {speed}  |  ETA: {eta}")

    def on_download_finished(self, success):
        self.download_thread.quit()
        self.download_thread.wait()
        
        self.download_btn.setEnabled(True)
        self.analyze_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if success:
            self.progress_bar.setValue(100)
            self.progress_status_label.setText("Download completed successfully.")

    def cancel_operation(self):
        if self.analysis_worker and self.analysis_thread and self.analysis_thread.isRunning():
            self.analysis_worker.cancel()
            self.analysis_thread.quit()
            self.analysis_thread.wait()
            self.append_log("[!] Metadata analysis cancelled.")
            self.analyze_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.info_label.setText("Analysis cancelled.")

        if self.download_worker and self.download_thread and self.download_thread.isRunning():
            self.download_worker.cancel()
            self.download_thread.quit()
            self.download_thread.wait()
            self.cancel_btn.setEnabled(False)
            self.download_btn.setEnabled(True)
            self.analyze_btn.setEnabled(True)
            self.progress_status_label.setText("Operation cancelled. Zombie files purged.")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = YouTubeDownloaderApp()
    window.show()
    sys.exit(app.exec())