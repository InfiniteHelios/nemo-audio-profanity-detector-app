import os
import typing
from PyQt5.QtCore import QObject, pyqtSlot, QThread, pyqtSignal, QDir, QFile
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QFileDialog
from PyQt5.QtCore import pyqtSlot
import subprocess
import time
import nemo.collections.asr as nemo_asr
import numpy as np

from ui.main_window_ui import Ui_MainWindow
from waitingspinnerwidget import QtWaitingSpinner


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.model_thread = None
        self.convert_thread = None
        self.api_thread = None
        self.asr_model = None
        self.file = None
        self.bad_words = []

        # spinner
        self.spinner = QtWaitingSpinner(self)
        self.spinner.setRoundness(70.0)
        self.spinner.setMinimumTrailOpacity(15.0)
        self.spinner.setTrailFadePercentage(70.0)
        self.spinner.setNumberOfLines(12)
        self.spinner.setLineLength(10)
        self.spinner.setLineWidth(5)
        self.spinner.setInnerRadius(10)
        self.spinner.setRevolutionsPerSecond(1)
        self.spinner.setColor(QColor(81, 4, 71))

    def closeEvent(self, event):
        super(QMainWindow, self).closeEvent(event)
        try:
            if self.api_thread:
                self.api_thread.terminate()
                self.api_thread.exit(-1)
                self.api_thread.quit()
                self.api_thread.deleteLater()
            if self.model_thread:
                self.model_thread.terminate()
                self.model_thread.exit(-1)
                self.model_thread.quit()
                self.model_thread.deleteLater()
            if self.convert_thread:
                self.convert_thread.terminate()
                self.convert_thread.exit(-1)
                self.convert_thread.quit()
                self.convert_thread.deleteLater()
        except:
            pass

    @pyqtSlot()
    def on_btnLoadModel_clicked(self):
        if self.asr_model:
            return
        try:
            self.statusBar().showMessage("Loading model...")
            self.spinner.start()
            self.centralWidget().setEnabled(False)
            self.model_thread = ModelLoadingThread("stt_en_jasper10x5dr.nemo", self)
            self.model_thread.finished.connect(self.onModelLoadingFinished)
            self.model_thread.start()
        except Exception as err:
            QMessageBox.critical(self, "Error", err)

    def onModelLoadingFinished(self, asr_model):
        self.asr_model = asr_model
        self.spinner.stop()
        self.centralWidget().setEnabled(True)
        self.statusBar().showMessage("Model prepaired")
        self.btnLoadModel.setEnabled(False)
        self.model_thread.terminate()
        self.model_thread.deleteLater()

    @pyqtSlot()
    def on_btnOpen_clicked(self):
        file = QFileDialog.getOpenFileName(
            self, "Open audio file", "", "Audio Files (*.m4a *.mp3 *.wma)"
        )[0]
        if not file:
            return
        self.file = file
        self.edtFilePath.setText(self.file)

    def get_bad_words(self):
        try:
            text = " ".join(self.txtBadWords.toPlainText().lower().split())
            self.bad_words = [item.strip() for item in text.split(",")] if text else []
        except Exception as err:
            QMessageBox.critical(self, "Error", err)

    @pyqtSlot()
    def on_btnStart_clicked(self):
        if not self.asr_model:
            QMessageBox.critical(self, "Error", "Please load model first.")
            return
        if not self.file:
            QMessageBox.critical(self, "Error", "Please open audio file to detect.")
            return
        self.get_bad_words()
        if not len(self.bad_words):
            QMessageBox.critical(self, "Error", "Please type bad words.")
            return
        try:
            self.spinner.start()
            self.listResult.clear()
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Converting audio file to wav...")
            outfile = QDir.currentPath() + "/outfile.wav"
            self.convert_thread = ConvertThread(self.file, outfile, parent=self)
            self.file = outfile
            self.convert_thread.finished.connect(self.onConvertingFinished)
            self.convert_thread.finished.connect(self.convert_thread.deleteLater)
            self.convert_thread.start()
        except Exception as err:
            QMessageBox.critical(self, "Error", err)

    def onConvertingFinished(self):
        try:
            self.statusBar().showMessage("Audio file is converted to wav")
            self.convert_thread.terminate()
            self.convert_thread.deleteLater()
            self.api_thread = DetectorThread(
                self.file, self.bad_words, self.asr_model, parent=self
            )
            self.api_thread.progress.connect(self.onDetectingProgress)
            self.api_thread.finished.connect(self.onDetectingFinished)
            self.api_thread.finished.connect(self.api_thread.deleteLater)
            self.api_thread.start()
            self.statusBar().showMessage("Transcribing...")
        except Exception as err:
            QMessageBox.critical(self, "Error", "onConvertingFinished: " + err)

    def onDetectingProgress(self, result: str):
        if not result:
            return
        self.listResult.addItem(result)

    def onDetectingFinished(self):
        self.api_thread.terminate()
        self.api_thread.deleteLater()
        self.spinner.stop()
        self.centralWidget().setEnabled(True)
        self.statusBar().showMessage("Detection is finished.")
        QMessageBox.information(
            self, "Info", "Finished detection.\nPlease check the result list."
        )


class ModelLoadingThread(QThread):
    finished = pyqtSignal(object)

    def __init__(self, model_path, parent: typing.Optional[QObject] = ...) -> None:
        super().__init__(parent=parent)
        self.model_path = model_path

    def run(self):
        try:
            asr_model = nemo_asr.models.EncDecCTCModel.restore_from(
                restore_path=self.model_path
            )
        except Exception as err:
            with open("log.txt", "a") as f:
                f.write(str(err))
        finally:
            self.finished.emit(asr_model)


class ConvertThread(QThread):
    finished = pyqtSignal()

    def __init__(self, file, outfile, parent: typing.Optional[QObject] = ...) -> None:
        super().__init__(parent=parent)
        self.file = file
        self.outfile = outfile

    def run(self):
        try:
            QFile.remove(self.outfile)
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(
                [
                    "ffmpeg",
                    "-loglevel",
                    "quiet",
                    "-i",
                    self.file,
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    self.outfile,
                ],
                stdout=subprocess.PIPE,
            )
        except Exception as err:
            with open("log.txt", "a") as f:
                f.write(str(err))
        finally:
            self.finished.emit()


class DetectorThread(QThread):
    finished = pyqtSignal()
    progress = pyqtSignal(str)

    def __init__(
        self, file, bad_words, asr_model, parent: typing.Optional[QObject] = ...
    ) -> None:
        super().__init__(parent=parent)
        self.file = file
        self.bad_words = bad_words
        self.asr_model = asr_model
        self.process = None

    def softmax(self, logits):
        e = np.exp(logits - np.max(logits))
        return e / e.sum(axis=-1).reshape([logits.shape[0], 1])

    def run(self):
        try:
            # transcribe audio
            transcript = self.asr_model.transcribe(paths2audio_files=[self.file])[0]

            # extract timestamps and split words
            logits = self.asr_model.transcribe([self.file], logprobs=True)[0]
            probs = self.softmax(logits)

            # 20ms is duration of a timestep at output of the model
            time_stride = 0.02

            # get timestamps for space symbols
            spaces = []

            state = ""
            idx_state = 0

            if np.argmax(probs[0]) == 0:
                state = "space"

            for idx in range(1, probs.shape[0]):
                current_char_idx = np.argmax(probs[idx])
                if (
                    state == "space"
                    and current_char_idx != 0
                    and current_char_idx != 28
                ):
                    spaces.append([idx_state, idx - 1])
                    state = ""
                if state == "":
                    if current_char_idx == 0:
                        state = "space"
                        idx_state = idx

            if state == "space":
                spaces.append([idx_state, len(probs) - 1])
            # calibration offset for timestamps: 180 ms
            offset = -0.18
            # split the transcript into words
            words = transcript.split()
            # cut words
            pos_prev = 0
            for j, spot in enumerate(spaces):
                pos_end = offset + (spot[0] + spot[1]) / 2 * time_stride
                if [ele for ele in self.bad_words if (ele in words[j + 1])]:
                    result = "%s Start: %s End: %s" % (
                        words[j + 1],
                        time.strftime("%H:%M:%S", time.gmtime(pos_prev)),
                        time.strftime("%H:%M:%S", time.gmtime(pos_end)),
                    )
                    self.progress.emit(result)
                pos_prev = pos_end
        except Exception as err:
            with open("log.txt", "a") as f:
                f.write(str(err))
        finally:
            self.finished.emit()
