"""
    SALTS XBMC Addon
    Copyright (C) 2014 tknorris

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import scraper
import json
import xbmcaddon
import xbmc
import urlparse
from salts_lib import log_utils
from salts_lib.constants import VIDEO_TYPES
from salts_lib.constants import QUALITIES
from salts_lib.constants import SORT_KEYS

from salts_lib.db_utils import DB_Connection
BASE_URL = ''

class Local_Scraper(scraper.Scraper):
    def __init__(self, timeout=scraper.DEFAULT_TIMEOUT):
        self.db_connection = DB_Connection()
        self.base_url = xbmcaddon.Addon().getSetting('%s-base_url' % (self.get_name()))
        self.def_quality = int(xbmcaddon.Addon().getSetting('%s-def-quality' % (self.get_name())))

    @classmethod
    def provides(cls):
        return frozenset([VIDEO_TYPES.TVSHOW, VIDEO_TYPES.SEASON, VIDEO_TYPES.EPISODE, VIDEO_TYPES.MOVIE])

    @classmethod
    def get_name(cls):
        return 'Local'

    def resolve_link(self, link):
        return link

    def format_source_label(self, item):
        return '[%s] %s (%s views)' % (item['quality'], item['host'], item['views'])

    def get_sources(self, video):
        source_url = self.get_url(video)
        hosters = []
        if source_url:
            params = urlparse.parse_qs(source_url)
            if video.video_type == VIDEO_TYPES.MOVIE:
                cmd = '{"jsonrpc": "2.0", "method": "VideoLibrary.GetMovieDetails", "params": {"movieid": %s, "properties" : ["file", "playcount", "streamdetails"]}, "id": "libMovies"}'
                result_key = 'moviedetails'
            else:
                cmd = '{"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodeDetails", "params": {"episodeid": %s, "properties" : ["file", "playcount", "streamdetails"]}, "id": "libTvShows"}'
                result_key = 'episodedetails'

            run = cmd % (params['id'][0])
            meta = xbmc.executeJSONRPC(run)
            meta = json.loads(meta)
            log_utils.log('Source Meta: %s' % (meta), xbmc.LOGDEBUG)
            if 'result' in meta and result_key in meta['result']:
                details = meta['result'][result_key]
                def_quality = [item[0] for item in sorted(SORT_KEYS['quality'].items(), key=lambda x:x[1])][self.def_quality]
                host = {'multi-part': False, 'class': self, 'url': details['file'], 'host': 'XBMC Library', 'quality': def_quality, 'views': details['playcount'], 'rating': None, 'direct': True}
                stream_details = details['streamdetails']
                if len(stream_details['video']) > 0 and 'width' in stream_details['video'][0]:
                    host['quality'] = self._width_get_quality(stream_details['video'][0]['width'])
                hosters.append(host)
        return hosters

    def get_url(self, video):
        temp_video_type = video.video_type
        if video.video_type == VIDEO_TYPES.EPISODE: temp_video_type = VIDEO_TYPES.TVSHOW
        url = None

        results = self.search(temp_video_type, video.title, video.year)
        if results:
            url = results[0]['url']

        if url and video.video_type == VIDEO_TYPES.EPISODE:
            show_url = url
            url = self._get_episode_url(show_url, video)

        return url

    def _get_episode_url(self, show_url, video):
        params = urlparse.parse_qs(show_url)
        cmd = '{"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": {"tvshowid": %s, "season": %s, "filter": {"field": "%s", "operator": "is", "value": "%s"}, \
        "limits": { "start" : 0, "end": 25 }, "properties" : ["title", "season", "episode", "file", "streamdetails"], "sort": { "order": "ascending", "method": "label", "ignorearticle": true }}, "id": "libTvShows"}'
        base_url = 'video_type=%s&id=%s'
        episodes = []

        force_title = self._force_title(video)

        if not force_title:
            run = cmd % (params['id'][0], video.season, 'episode', video.episode)
            meta = xbmc.executeJSONRPC(run)
            meta = json.loads(meta)
            log_utils.log('Episode Meta: %s' % (meta), xbmc.LOGDEBUG)
            if 'result' in meta and 'episodes' in meta['result']:
                episodes = meta['result']['episodes']
        else:
            log_utils.log('Skipping S&E matching as title search is forced on: %s' % (video.slug), xbmc.LOGDEBUG)

        if (force_title or xbmcaddon.Addon().getSetting('title-fallback') == 'true') and video.ep_title:
            run = cmd % (params['id'][0], video.season, 'title', video.ep_title)
            meta = xbmc.executeJSONRPC(run)
            meta = json.loads(meta)
            log_utils.log('Episode Title Meta: %s' % (meta), xbmc.LOGDEBUG)
            if 'result' in meta and 'episodes' in meta['result']:
                episodes = meta['result']['episodes']

        for episode in episodes:
            if episode['file'].endswith('.strm'):
                continue
            
            return base_url % (video.video_type, episode['episodeid'])

    @classmethod
    def get_settings(cls):
        settings = super(Local_Scraper, cls).get_settings()
        name = cls.get_name()
        settings.append('         <setting id="%s-def-quality" type="enum" label="     Default Quality" values="None|Low|Medium|High|HD" default="0" visible="eq(-6,true)"/>' % (name))
        return settings

    def search(self, video_type, title, year):
        filter_str = '{"field": "title", "operator": "contains", "value": "%s"}' % (title)
        if year: filter_str = '{"and": [%s, {"field": "year", "operator": "is", "value": "%s"}]}' % (filter_str, year)
        if video_type == VIDEO_TYPES.MOVIE:
            cmd = '{"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": { "filter": %s, "limits": { "start" : 0, "end": 25 }, "properties" : ["title", "year", "file", "streamdetails"], \
            "sort": { "order": "ascending", "method": "label", "ignorearticle": true } }, "id": "libMovies"}'
            result_key = 'movies'
            id_key = 'movieid'
        else:
            cmd = '{"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows", "params": { "filter": %s, "limits": { "start" : 0, "end": 25 }, "properties" : ["title", "year"], \
            "sort": { "order": "ascending", "method": "label", "ignorearticle": true } }, "id": "libTvShows"}'
            result_key = 'tvshows'
            id_key = 'tvshowid'

        results = []
        cmd = cmd % (filter_str)
        meta = xbmc.executeJSONRPC(cmd)
        meta = json.loads(meta)
        log_utils.log('Search Meta: %s' % (meta), xbmc.LOGDEBUG)
        if 'result' in meta and result_key in meta['result']:
            for item in meta['result'][result_key]:
                if video_type == VIDEO_TYPES.MOVIE and item['file'].endswith('.strm'):
                    continue

                result = {'title': item['title'], 'year': item['year'], 'url': 'video_type=%s&id=%s' % (video_type, item[id_key])}
                results.append(result)
        return results
