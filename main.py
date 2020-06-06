import youtube_dl
import re
from requests import get
from html import unescape
from json import loads, dumps
from os import chdir, rename
from pathlib import Path
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
import qdarkstyle
import traceback, sys

class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    info = pyqtSignal(str)

class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()    

        # Add the callback to our kwargs
        self.kwargs['infoCallback'] = self.signals.info    

    @pyqtSlot()
    def run(self):
        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.signals.finished.emit()  # Done

class Ui_Dialog(object):
    def __init__(self, url, path, all):
        self.all = all
        # list of bools for every playlist in all, in the beginning all True, meaning all are selected
        self.selected = [[True] * len(i[1]) for i in self.all]
        self.playlistTitles = [i[0][0] for i in self.all]
        self.comboBoxIndex = 0
        self.path = path.replace("\\", "//")
        self.countSelectAll = [0] * len(self.all)
        self.data = None
        
    def _add_items_to_listWidget(self, index):
        select = self.selected[index]
        songs = self.all[index][1]
        for i in range(len(songs)):
            item = QListWidgetItem()
            # set text to song title
            item.setText(songs[i][0])
            if select[i]:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.listWidget.addItem(item)

    def saveSelection(self, index):
        select = self.selected[index]
        for i in range(len(select)):
            item = self.listWidget.item(i)
            if item.checkState() == Qt.Checked:
                select[i] = True
            else:
                select[i] = False
        self.selected[index] = select
    
    def switchSelection(self):
        state = self.countSelectAll[self.comboBoxIndex]%2 == 0
        length = self.listWidget.count()
        for i in range(length):
            item = self.listWidget.item(i)
            if state:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.Checked)
        self.countSelectAll[self.comboBoxIndex] += 1

    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(500, 550)
        self.dialog = Dialog
        # optionen 1-4 box oben
        self.comboBox = QComboBox(Dialog)
        # left top point, width, height
        self.comboBox.setGeometry(QRect(10, 20, 480, 30))
        self.comboBox.setObjectName("comboBox")
        self.comboBox.addItems(self.playlistTitles)
        self.comboBox.currentIndexChanged.connect(self.selectionchange)
        
        self.listWidget = QListWidget(Dialog)
        self.listWidget.setGeometry(QRect(10, 60, 480, 400))
        self.listWidget.setObjectName("listWidget")
        self.listWidget.setSelectionMode(QAbstractItemView.NoSelection)
        self._add_items_to_listWidget(0)

        self.retranslateUi(Dialog)
        QMetaObject.connectSlotsByName(Dialog)
        
        self.bStart = QPushButton(Dialog)
        self.bStart.setGeometry(QRect(260, 490, 230, 30))
        self.bStart.clicked.connect(self.start)
        self.bStart.setText("Start")

        self.selector = QPushButton(Dialog)
        self.selector.setGeometry(10, 490, 230, 30)
        self.selector.clicked.connect(self.switchSelection)
        self.selector.setText("(De-)select all")

    def retranslateUi(self, Dialog):
        _translate = QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Choose your songs"))

    def selectionchange(self, newComboBoxIndex):
        self.saveSelection(self.comboBoxIndex)
        self.listWidget.clear() 
        self.comboBoxIndex = newComboBoxIndex
        self._add_items_to_listWidget(newComboBoxIndex)

    def start(self):
        self.saveSelection(self.comboBoxIndex)
        self.data = selectToDownload(self.all, self.selected)
        self.dialog.accept()

class App(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = None
        self.url = None
        self.path = None
        self.playlists = None
        self.playlistIndex = 0
        self.dataSave = {}
        self.headers = {'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36'}
        self.threadpool = QThreadPool()
        self.initUI()

    def initUI(self):
        self.createLogger()
        self.getURL()
        self.getPath()
        self.getData(self.url)
    
    def log(self, s):
        self.logger.appendPlainText(s)

    def getURL(self):
        url, okPressed = QInputDialog().getText(self, "Get URL","Your URL:", QLineEdit.Normal, "")
        if okPressed and url != '':
            self.url = url
            self.log("URL: "+url)
        else:
            raise Exception("Invalid URL")
        
    def getPath(self):
        self.path = str(QFileDialog.getExistingDirectory(self, "Select Directory"))
        if self.path:
            self.log("Path: "+self.path)
        else:
            raise Exception("Invalid Path")

    def createLogger(self):
        screen = QDesktopWidget().screenGeometry(-1)
        height = screen.height()
        self.logger = QPlainTextEdit("")
        self.logger.setFont(QFont('Helvetica', height//80))
        self.logger.showMaximized()

    def startDialog(self, data):
        Dialog = QDialog(self)
        ui = Ui_Dialog(self.url, self.path, data)
        ui.setupUi(Dialog)
        if Dialog.exec_() == QDialog.Accepted:
            self.data = ui.data
            self.downloadNextPlaylist()

    def finished(self):
        if self.threadpool.activeThreadCount() == 0:
            data = [[pl, self.dataSave[pl]] for pl in self.playlists]
            self.startDialog(data)

    """given an url returns the data in the required format for downloadMultiplePlaylists(self, data, path)"""
    def getData(self, url):
        # https://www.youtube.com/watch?v=xGY0eRpV9Qw Video
        # https://www.youtube.com/watch?v=1SH1PqOEGnE&list=PLt_47Imx98wqRAOoZ4iehs16jctcdXAPm&index=2&t=0s Playlist
        # https://www.youtube.com/playlist?list=PLt_47Imx98wqRAOoZ4iehs16jctcdXAPm Playlist
        # https://www.youtube.com/channel/UCPmCaKjzYF3pXYLfaRhacwA Channel
        vYt = "https://www.youtube.com/watch?v="
        plYt = "https://www.youtube.com/playlist?list="
        if "channel" in url:
            self.log("Found Channel")
            self.log("Searching for playlists in channel")
            self.playlists = self.playlistTitlesIds(self.getChannelURL(url))
            # use multithreading to extract the data from multiple playlists at the same time
            for pl in self.playlists:
                plTitle, plId = pl[0], pl[1]
                worker = Worker(self.getPlaylistDataThread, plTitle, plId)
                worker.signals.info.connect(self.log)
                worker.signals.finished.connect(self.finished)
                self.threadpool.start(worker)
        elif "list" in url:
            self.log("Found Playlist")
            self.log("Searching for songs in playlist")
            self.log("Please wait")
            plId = re.compile(r"list=([\w-]*)").findall(url)[0]
            playlistInfo = (get_title(plYt + plId), plId)
            url = plYt + plId
            playlistContent = self.titleIds(url)
            if len(playlistContent) == 1:
                self.log("Found 1 song in "+ playlistInfo[0])
            else:
                self.log("Found "+ str(len(playlistContent))+ " songs in "+ playlistInfo[0])
            data = [[playlistInfo, playlistContent]]
            self.startDialog(data)
        elif "watch" in url:
            self.log("Found Youtube video")
            vId = re.compile(r"watch\?v=([\w-]*)").findall(url)[0]
            url = vYt + vId
            title = get_title(url)
            data = [[(title, vId), [(title, vId)]]]
            self.startDialog(data)
        else:
            # if neither channel, playlist, or video not able to extract
            raise Exception("INVALID URL")
    
    """returns list of playlists with their titles and ids given an channel url"""
    def playlistTitlesIds(self, url):
        # open url
        searched = get(url,headers=self.headers).text
        # youtube saves the playlist information of the playlists in a json object named "ytInitialData"
        ytInitialData = loads(re.compile(r"window\[\"ytInitialData\"\] = ([^;]*)").findall(searched)[0])
        items = ytInitialData["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][2]["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"][0]["gridRenderer"]["items"]
        # exctract information
        titles = []
        ids = []
        i = 0
        while True:
            try:
                titles.append(items[i]["gridPlaylistRenderer"]["title"]["runs"][0]["text"])
                ids.append(items[i]["gridPlaylistRenderer"]["playlistId"])
                i += 1
            except:
                break
        return list(zip(titles, ids))

    def getChannelURL(self, url):
        beginning = "https://www.youtube.com/channel/"
        channelId = re.compile(r"channel/([\w-]*)").findall(url)[0]
        return beginning + channelId + "/playlists"

    """returns a list of the data in a playlist in the form [(videoTitle, videoId),...]"""
    def titleIds(self, url):
        # youtube saves the playlist information of the first 100 videos in a json object named "ytInitialData"
        searched = get(url,headers=self.headers).text
        ytInitialData = loads(re.compile(r"window\[\"ytInitialData\"\] = ([^;]*)").findall(searched)[0])
        items = ytInitialData["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"][0]["playlistVideoListRenderer"]
        titles = []
        ids = []
        for i in range(100):
            try:
                item = items["contents"][i]["playlistVideoRenderer"]
                titles.append(item["title"]["simpleText"])
                ids.append(item["videoId"])
            except:
                # video not available, deleted ...
                pass
        # if there are more than 100 songs ajax calls are made
        try:
            # save continuation
            cont = items["continuations"][0]["nextContinuationData"]["continuation"]
        except:
            # not more than 100 videos in playlist
            return list(zip(titles, ids))
        # ajax call
        url = "https://www.youtube.com/browse_ajax?action_continuation=1&amp;continuation=" + cont
        # as long as continuations exist
        while url:
            # try opening the url multiple times to make sure it was not a periodic error
            count = 0
            while count < 3:
                html = get(url).text
                # response is an json object with a load_more_widget_html parameter where the continuation of the ajax call is and content_html with the html of the newly loaded content
                j = loads(html)
                try:
                    load_more = dumps(j["load_more_widget_html"], ensure_ascii=False)
                    content = dumps(j["content_html"], ensure_ascii=False)
                except:
                    count += 1
                    continue
                # exctract titles and ids from new content, titles are with html entities so we have to escape that
                titles += [unescape(i) for i in re.compile(r"data-title=\\\"(.*?)\\\"").findall(content)]
                ids += re.compile(r"data-video-id=\\\"(.*?)\\\"").findall(content)
                # load next ajax call
                match = re.search(
                    r"data-uix-load-more-href=\\\"(.*?)\\\"",
                    load_more,
                )
                if match:
                    url = f"https://www.youtube.com{match.group(1)}"
                else:
                    url = None
                break
        # combine the titles and ids
        return list(zip(titles, ids))

    """manages to extract info from multiple playlists at the same time"""
    def getPlaylistDataThread(self, plTitle, plId, infoCallback):
        plYt = "https://www.youtube.com/playlist?list="
        url = plYt + plId
        # run extraction
        data = self.titleIds(url)
        # save extracted data in dict
        self.dataSave[(plTitle, plId)] = data
        if len(data) == 1:
            infoCallback.emit("Found 1 song in "+plTitle)
        else:
            infoCallback.emit("Found "+str(len(data))+ " songs in "+plTitle)

    """downloads all playlists in data in path, creates folders for every playlist
    data: [[(playlistTitle, playlistId), [(videoTitle, videoId), ...]], ...]
    """
    def downloadNextPlaylist(self):
        # change working directory
        chdir(self.path)
        playlist, songs = self.data[self.playlistIndex][0], self.data[self.playlistIndex][1]
        plTitle = playlist[0]
        self.log("Creating new directory for "+plTitle)
        folder = self.path + "/" + plTitle
        # create folder, any missing parents are created, ok if folder already exists
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.downloadPlaylist(songs, folder)

    def finishedDownloadVideo(self):
        if self.threadpool.activeThreadCount() == 0:
            self.playlistIndex += 1
            if self.playlistIndex < len(self.data):
                self.downloadNextPlaylist()
            else:
                self.log("FINISHED")

    """ downloads all videos in a playlist given songs using multithreading"""
    def downloadPlaylist(self, songs, folder):
        # change working directory
        chdir(folder)
        self.log("Start downloading "+ str(len(songs))+ " songs")
        for song in songs:
            songTitle, songId = song[0], song[1]
            worker = Worker(self.downloadVideo, songTitle, songId)
            worker.signals.info.connect(self.log)
            worker.signals.finished.connect(self.finishedDownloadVideo)
            self.threadpool.start(worker)

    def downloadVideo(self, title, Id, infoCallback):
        params = {
            'format': 'bestaudio/best',
            'quiet': True,
            'outtmpl': '%(title)s.%(ext)s',
            'logger': MyLogger(infoCallback),
            'postprocessors': [
                {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
                },
                {'key': 'FFmpegMetadata'}
            ],
        }
        try:
            info = youtube_dl.YoutubeDL(params).extract_info(Id, download = True)
            if info["alt_title"] != None:
                title = info["alt_title"]
            # modify the filename the way youtube_dl does it
            filename = info["title"]
            new = newName(title)
            # replace certain characters with others
            toReplace = {"/":"_", "|":"_", "?":"", '"':"'", ":":" -"}
            for k, v in toReplace.items():
                filename = filename.replace(k, v)
                new = new.replace(k, v)
            # replace multiple underscores with a single one
            filename = re.sub("_+", "_", filename)
            new = re.sub("_+", "_", new)
            # remove trailing underscore
            if filename[-1] == "_":
                filename = filename[:-1]
            if new[-1] == "_":
                new = new[:-1]
            new = new.strip()
            # rename the file
            infoCallback.emit("Finished Downloading "+new)
            rename(filename+".mp3", new+".mp3")
        except:
            pass

"""returns the string s without some words and the content in (), [] or {}"""
def newName(s):
    words = ["Audio", "AUDIO", "audio", "Video", "VIDEO", "video", "HD", "hd", "Hd", "lyrics", "LYRICS", "Lyrics", "HQ", "OFFICIAL", "Official", "official", "Karaoke", "karaoke", "KARAOKE", "Original", "ORIGINAL"]
    newName = ""
    add = True
    for c in s:
        if c in ("(", "[", "{"):
            add = False
            newName.rstrip()
        elif c in (")", "]", "}"):
            add = True
        elif add:
            newName += c
    for word in words:
        newName = newName.replace(word, "")
    return newName

"""returns title of a youtube video or playlist given an url"""
def get_title(url):
    count = 0
    while count < 3:
        # get htlm of url
        youtube = get(url).text
        # regex does not support " in name
        #res = re.compile(r"<meta name=\"title\" content=\"([^\"]*)").findall(youtube)
        for s in youtube.split("\n"):
            if s.find("meta") != -1 and s.find('name="title"') != -1:
                temp = s.split('"')[-2]
                return unescape(temp.replace(" - YouTube", ""))
    return ""

"""returns selected data from data and a selected list"""
def selectToDownload(allInfo, selected):
    new = []
    for i in range(len(allInfo)):
        new.append([])
        # add playlist title and id
        new[-1].append(allInfo[i][0])
        new[-1].append([])
        songs = []
        for j in range(len(allInfo[i][1])):
            if selected[i][j]:
                songs.append(allInfo[i][1][j])
        if len(songs) == 0:
            new.pop()
        else:
            new[-1][1] = songs
    return new

class MyLogger():
    def __init__(self, infoCallback):
        self.infoCallback = infoCallback

    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.infoCallback.emit(msg)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    ex = App()
    sys.exit(app.exec_())