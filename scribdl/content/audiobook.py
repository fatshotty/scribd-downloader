from bs4 import BeautifulSoup
import requests
import json
import re
import os

from .base import ScribdBase
from .. import internals
from .. import const
from .. import exceptions


folder_download = "Downloads"
folder_type = "Audiobooks"
folder_name = folder_download + "/" + folder_type

class Track:
    """
    A class for an audio chapter in a Scribd audiobook playlist.

    Parameters
    ----------
    track: `dict`
        A dictionary information about an audiobook chapter
        containing the keys: "url", "part_number" and "chapter_number".
    """

    def __init__(self, track):
        self.url = track["url"]
        self.part_number = track["part_number"]
        self.chapter_number = track["chapter_number"]
        self._track = track

    def download(self, path):
        """
        Downloads the audiobook chapter to the given path.
        """
        internals.download_stream(self.url, path)


class Playlist:
    """
    A class for a Scribd audiobook playlist.

    Parameters
    ----------
    title: `str`
        The title of the audiobook.

    playlist: `dict`
        A dictionary information about an audiobook playlist and
        its tracks containing the keys: "playlist", "expires" and
        "playlist_token".
    """

    def __init__(self, title, playlist):
        self.title = title
        self.sanitized_title = internals.sanitize_title(title)
        self.tracks = [ Track(track) for track in playlist["playlist"] ]
        self._playlist = playlist
        self.download_paths = []

    def download(self):
        """
        Downloads all the chapters available in the playlist.
        """
        full_folder = folder_name + "/" + self.title
        try:
            os.stat(folder_download)
        except:
            os.mkdir(folder_download)
        try:
            os.stat(folder_name)
        except:
            os.mkdir(folder_name)
        try:
            os.stat(full_folder)
        except:
            os.mkdir(full_folder)

        for track in self.tracks:

            path = "{0}/{1}_{2}.mp3".format(full_folder, self.sanitized_title, track.chapter_number)
            dl_str = 'Downloading chapter-{0} ({1}) to "{2}"'.format(track.chapter_number,
                                                                   track.url,
                                                                   path)
            print(dl_str)
            track.download(path)
            self.download_paths.append(path)


class ScribdAudioBook(ScribdBase):
    """
    A base class for downloading audiobooks off Scribd.

    Parameters
    ----------
    url: `str`
        A string containing Scribd audiobook URL.
    """

    def __init__(self, audiobook_url):
        super().__init__(audiobook_url)
        scribd_id_search = re.search("[0-9]{9}", audiobook_url)
        scribd_id = scribd_id_search.group()

        self._audiobook_keys= None
        self._book_id = None
        self._author_id = None
        self._license_id = None
        self._playlist = None

        self._user_id = None

        self.audiobook_url = audiobook_url
        self.scribd_id = scribd_id

        print('found book id: {}'.format(scribd_id))

        # Replace these cookie values with ones generated when logged into a
        # Scribd premium-account. This will allow access to full audiobooks.
        self.cookies = const.premium_cookies

    @property
    def audiobook_keys(self):
        """
        Stores scraped information for an audiobook.
        """
        if not self._audiobook_keys:
            audiobook_keys = self._scrape_audiobook_page()
            try:
                print('getting AUTH keys...')
                authenticate_page_keys = self._scrape_authentication_page()
                print('correctly GOT AUTH keys!!')
            except exceptions.ScribdFetchError:
                print('*** CANNOT GET AUTH KEY')
                pass
            else:
                audiobook_keys.update(authenticate_page_keys)
            self._audiobook_keys = audiobook_keys
        return self._audiobook_keys

    @property
    def session_key(self):
        """
        Returns the Scribd session key used to communicate with https://api.findawayworld.com/.
        """
        try:
            session_key = self.audiobook_keys["audiobook"]["session_key"]
        except KeyError:
            session_key = None
        return session_key

    @property
    def headers(self):
        """
        Constructs headers to pass with the network request.
        """
        return {"Session-Key": self.session_key}

    @property
    def preview_url(self):
        """
        The free-to-access URL of the audiobook.
        """
        return self.audiobook_keys["preview_url"]

    @property
    def book_id(self):
        """
        The Book-ID of the audiobook.
        """
        if not self._book_id:
            audiobook = self.audiobook_keys
            self._book_id = audiobook["book_id"]
        return self._book_id

    @property
    def author_id(self):
        """
        The Author-ID of Scribd used to authenticate with
        https://api.findawayworld.com/.
        """
        if not self._author_id:
            audiobook = self.audiobook_keys
            self._author_id = audiobook["author_id"]
        return self._author_id
    
    @property
    def user_id(self):
        """
        The User-ID of Scribd used to authenticate with
        https://api.findawayworld.com/.
        """
        if not self._user_id:
            audiobook = self.audiobook_keys
            self._user_id = audiobook["user_id"]
        return self._user_id

    @property
    def license_url(self):
        """
        Returns the URL used to fetch the License-ID.
        """
        return "https://api.findawayworld.com/v4/accounts/scribd-{0}/audiobooks/{1}".format(self.user_id, self.book_id)

    @property
    def license_id(self):
        """
        Returns the License-ID to be used by Scribd to fetch
        the audiobook content from http://api.findawayworld.com/.
        """
        if not self._license_id:
            try:
                self._license_id = self._get_license_id()
            except exceptions.ScribdFetchError:
                self._license_id = None
        return self._license_id

    @property
    def playlist_url(self):
        """
        Returns the audiobook playlist URL.
        """
        return "https://api.findawayworld.com/v4/audiobooks/{}/playlists".format(self.book_id)

    @property
    def authenticate_url(self):
        """
        Authentication URL for premium Scribd accounts
        (if this didn't exist, we would have been able to download
        complete audiobooks off Scribd without needing a premium account).
        """
        return "https://www.scribd.com/listen/{}".format(self.scribd_id)

    @property
    def premium_cookies(self):
        """
        Returns a boolean based on whether the user is authenticated
        with a premium Scribd account.
        """
        try:
            premium_cookies = bool(self.license_id)
        except exceptions.ScribdFetchError:
            premium_cookies = False
        return premium_cookies

    @property
    def playlist(self):
        """
        Returns a `Playlist` object.
        """
        if not self._playlist:
            self._playlist = Playlist(self.title, self.make_playlist())
        return self._playlist

    def _get_license_id(self):
        """
        Scrapes the License-ID for the audiobook. We need to handle retries
        as Scribd can sometimes fail to deliver the License-ID in the HTML.
        """
        requests.get(self.authenticate_url, cookies=self.cookies)
        response = requests.get(self.license_url, headers=self.headers)
        response_dict = json.loads(response.text)
        try:
            license_id = response_dict["licenses"][0]["id"]
        except KeyError:
            raise exceptions.ScribdFetchError("Unable to fetch the License ID for the audiobook. This attribute"
                                              "is only available when using a premium Scribd account.")
        else:
            return license_id

    def download(self):
        raise NotImplementedError("Use method `ScribdAudioBook.playlist.download` instead.")

    def _scrape_audiobook_page(self):
        # """
        # Scrapes the provided audiobook URL for information scraps.
        # """
        print('scrape: {}'.format(self.audiobook_url))
        response = requests.get(self.audiobook_url, cookies=self.cookies)
        soup = BeautifulSoup(response.text, "html.parser")

        # div_tag = soup.find("div", {"data-track_category": "book_preview"})
        # text = json.loads(div_tag["data-push_state"])
        # preview_url = text["audiobook_sample_url"]
        # book_id_search = re.search("[0-9]{5,6}", preview_url)
        # book_id = book_id_search.group()

        # js_tag = soup.find_all("script", {"type": "text/javascript"})[-1]
        # js_code = js_tag.get_text()
        # author_id_search = re.search("[0-9]{8,9}", js_code)
        # author_id = author_id_search.group() if author_id_search else None

        # return {"preview_url": preview_url, "book_id": book_id, "author_id": author_id}

        script_tag = soup.find("script", {"data-hypernova-key": "contentpreview"})
        content_json = script_tag.string
        # print('json: {}'.format(content_json))
        content_json = content_json.replace('<!--', '').replace('-->', '')
        json_data = json.loads(content_json)
        author_id = json_data['contentItem']['author']['id']

        preview_url = json_data['contentItem']['audioSampleUrl']
        book_id_search = re.search("[0-9]{5,6}", preview_url)
        book_id = book_id_search.group()

        user_id = json_data['user']['id']

        audiobookdata = {"preview_url": preview_url, "book_id": book_id, "author_id": author_id, "user_id": user_id}
        print('audiobook_keys: {}'.format(audiobookdata))

        return audiobookdata

    def _scrape_authentication_page(self):
        """
        Scrapes the authentication/listen page of the audiobook
        for information scraps.
        """
        response = requests.get(self.authenticate_url, cookies=self.cookies)
        soup = BeautifulSoup(response.text, "html.parser")
        # js_tag = soup.find_all("script", {"type": "text/javascript"})[-2]

        # try:
        print('scaping {}'.format(self.authenticate_url) )
        # print(response.text)
        find_index = response.text.find('{"eor_url":')
        start = response.text[find_index:]
        # print( 'start {}'.format(start) )
        raw_info_str = start.split("\n")[0]
        index = raw_info_str.find("}}})")
        raw_info_str = raw_info_str[ 0 : index + 3 ]

        # print( 'parse:  {}'.format(raw_info_str) )

        info_dict = json.loads(raw_info_str)
        info_dict["pingback_url"] = "".join(info_dict["pingback_url"])
        # except ValueError:
        #     raise exceptions.ScribdFetchError("Unable to fetch information via the authentication page for the"
        #                                       "audiobook. This is only available when using a premium Scribd account.")
        # else:
        return info_dict

    def make_playlist(self):
        """
        Generates a playlist dictionary based on whether the user
        is authenticated with a premium Scribd account or not.
        """
        if self.premium_cookies:
            data = '{"license_id":"' + self.license_id + '"}'
            print( 'license ID: {}'.format(self.license_id) )
            response = requests.post(self.playlist_url, headers=self.headers, data=data)
            playlist = json.loads(response.text)
        else:
            playlist = {"playlist": [{"url": self.preview_url,
                                     "part_number": "preview",
                                     "chapter_number": "preview"}],
                        "expires": None,
                        "playlist_token": None}

        return playlist
