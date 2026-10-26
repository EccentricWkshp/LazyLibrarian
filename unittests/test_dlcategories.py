#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the download categories, one per media type for each download client: moving the shared
#   settings to them, looking them up, and the clients sending and checking them

import contextlib
from unittest import mock

from lazylibrarian import deluge, dlcategories, rtorrent, sabnzbd
from lazylibrarian.config2 import LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


def config(**values):
    """ A config with the defaults, as if config.ini only had these values """
    cfg = LLConfigHandler(defaults=BASE_DEFAULTS)
    for key, value in values.items():
        if isinstance(value, int):
            cfg.set_int(key, value)
        else:
            cfg.set_str(key, value)
    return cfg


class FixupTest(LLTestCaseWithConfigandDIRS):

    @staticmethod
    def categories(cfg, base):
        return [cfg.get_str(f"{base}{suffix}") for suffix in ('', '_AUDIO', '_MAG', '_COMIC')]

    def test_a_new_install(self):
        cfg = config()
        self.assertEqual(cfg.fixup_download_categories(), 0)
        self.assertEqual(self.categories(cfg, 'QBITTORRENT_LABEL'), ['', '', '', ''])

    def test_one_category_for_everything_stays_that_way(self):
        cfg = config(SAB_CAT='books')
        self.assertEqual(cfg.fixup_download_categories(), 1)
        self.assertEqual(self.categories(cfg, 'SAB_CAT'), ['books'] * 4)

    def test_a_list_is_split_by_position(self):
        cfg = config(QBITTORRENT_LABEL='books, audiobooks', DELUGE_LABEL='ebooks,,mags,comics')
        self.assertEqual(cfg.fixup_download_categories(), 2)
        self.assertEqual(self.categories(cfg, 'QBITTORRENT_LABEL'), ['books', 'audiobooks', '', ''],
                         'Types missing from the list had no category')
        self.assertEqual(self.categories(cfg, 'DELUGE_LABEL'), ['ebooks', '', 'mags', 'comics'])

    def test_only_once(self):
        cfg = config(NZBGET_CATEGORY='books', NZBGET_CATEGORY_AUDIO='')
        cfg.fixup_download_categories()
        self.assertEqual(self.categories(cfg, 'NZBGET_CATEGORY'), ['books', '', 'books', 'books'],
                         'An empty category the user chose is kept')
        cfg.set_str('NZBGET_CATEGORY_MAG', 'magazines')
        self.assertEqual(cfg.fixup_download_categories(), 0)
        self.assertEqual(self.categories(cfg, 'NZBGET_CATEGORY'), ['books', '', 'magazines', 'books'])

    def test_saved(self):
        cfg = config(SAB_CAT='books,audiobooks')
        cfg.fixup_download_categories()
        saved = cfg.save_config_to_string()[1]
        for line in ('sab_cat = books', 'sab_cat_audio = audiobooks', 'sab_cat_mag = ', 'sab_cat_comic = '):
            self.assertIn(line, saved.splitlines(), 'An empty category is saved too, so it stays empty')

    def test_on_load(self):
        cfg = config(TRANSMISSION_LABEL='books,audiobooks')
        cfg.post_load_fixup()
        self.assertEqual(self.categories(cfg, 'TRANSMISSION_LABEL'), ['books', 'audiobooks', '', ''])


class LookupTest(LLTestCaseWithConfigandDIRS):

    def use(self, cfg):
        patch = mock.patch.object(dlcategories, 'CONFIG', cfg)
        patch.start()
        self.addCleanup(patch.stop)
        return cfg

    def test_download_category(self):
        self.use(config(QBITTORRENT_LABEL='books', QBITTORRENT_LABEL_AUDIO='audiobooks',
                        QBITTORRENT_LABEL_MAG='', QBITTORRENT_LABEL_COMIC='comics'))
        for library, category in (('eBook', 'books'), ('AudioBook', 'audiobooks'), ('magazine', ''),
                                  ('Magazine', ''), ('comic', 'comics'), ('Comic', 'comics'), ('', 'books')):
            self.assertEqual(dlcategories.download_category('QBITTORRENT', library), category, library)
        self.assertEqual(dlcategories.download_categories('QBITTORRENT'), {'books', 'audiobooks', 'comics'})
        self.assertEqual(dlcategories.download_category('SYNOLOGY_TOR', 'eBook'), '', 'No categories')

    def test_deluge_connections_share_settings(self):
        self.use(config(DELUGE_LABEL='books', DELUGE_LABEL_AUDIO='audio'))
        self.assertEqual(dlcategories.category_setting('DELUGERPC', 'AudioBook'), 'DELUGE_LABEL_AUDIO')
        self.assertEqual(dlcategories.download_category('DELUGEWEBUI', 'AudioBook'), 'audio')

    def test_a_config_that_was_not_loaded(self):
        self.use(config(UTORRENT_LABEL='books,audiobooks'))
        self.assertEqual(dlcategories.download_category('UTORRENT', 'AudioBook'), 'audiobooks')
        self.assertEqual(dlcategories.download_category('UTORRENT', 'eBook'), 'books')


class ClientTest(LLTestCaseWithConfigandDIRS):

    def use(self, cfg, *modules):
        for module in (dlcategories, *modules):
            patch = mock.patch.object(module, 'CONFIG', cfg)
            patch.start()
            self.addCleanup(patch.stop)
        return cfg

    @contextlib.contextmanager
    def sab(self, replies=None):
        """ Answer SABnzbd requests by mode, keep the urls asked for in self.urls """
        self.urls = []

        def get(url, **kwargs):
            self.urls.append(url)
            mode = url.split('mode=')[1].split('&')[0]
            return mock.Mock(json=mock.Mock(return_value=(replies or {}).get(mode, {'status': True,
                                                                                     'nzo_ids': ['nzo_1']})))
        with mock.patch.object(sabnzbd.requests, 'get', side_effect=get):
            yield

    def test_sabnzbd_files_each_type_under_its_category(self):
        self.use(config(SAB_HOST='sab', SAB_PORT=8080, SAB_CAT='books', SAB_CAT_AUDIO='audiobooks',
                        SAB_CAT_MAG='', SAB_CAT_COMIC=''), sabnzbd)
        with self.sab():
            self.assertEqual(sabnzbd.sab_nzbd('A Book', 'http://nzb/1', library='AudioBook'), ('nzo_1', ''))
            sabnzbd.sab_nzbd('A Magazine', 'http://nzb/2', library='magazine')
            sabnzbd.sab_nzbd('A Book', 'http://nzb/3', library='AudioBook', label='provider')
            sabnzbd.sab_nzbd(nzburl='queue', nzo_ids='nzo_1')
            sabnzbd.sab_nzbd(nzburl='history', nzo_ids='nzo_1')
        self.assertIn('cat=audiobooks', self.urls[0])
        self.assertNotIn('cat=', self.urls[1], 'No category for magazines')
        self.assertIn('cat=provider', self.urls[2], "A provider's own label wins")
        for url in self.urls[3:]:
            self.assertNotIn('cat', url, 'Jobs are found by id, whatever category they are in')

    def test_sabnzbd_checks_every_category(self):
        self.use(config(SAB_HOST='sab', SAB_PORT=8080, SAB_CAT='books', SAB_CAT_AUDIO='audiobooks',
                        SAB_CAT_MAG='books', SAB_CAT_COMIC=''), sabnzbd)
        replies = {'auth': {'auth': 'apikey'}, 'version': {'version': '4.3.0'}, 'get_cats': {'categories': ['*', 'books']}}
        with self.sab(replies):
            message, ok = sabnzbd.check_link()
        self.assertFalse(ok)
        self.assertIn('[audiobooks]', message)
        replies['get_cats']['categories'].append('audiobooks')
        with self.sab(replies):
            self.assertTrue(sabnzbd.check_link()[1])

    def test_rtorrent_label(self):
        self.use(config(RTORRENT_LABEL='books'), rtorrent)
        server = mock.MagicMock()
        server.download_list.return_value = ['ABC']
        with mock.patch.object(rtorrent, 'get_server', return_value=(server, '0.9.8')), \
                mock.patch.object(rtorrent, 'get_name', return_value='A Book'), \
                mock.patch.object(rtorrent, 'get_directory', return_value='/downloads'):
            self.assertEqual(rtorrent.add_torrent('http://t/1', 'abc', label='audiobooks'), ('abc', ''))
        server.load.start.assert_called_once_with('', 'http://t/1', 'd.custom1.set="audiobooks"')

    def test_deluge_checks_every_label(self):
        self.use(config(DELUGE_LABEL='books', DELUGE_LABEL_AUDIO='audiobooks', DELUGE_LABEL_MAG='books',
                        DELUGE_LABEL_COMIC=''), deluge)
        with mock.patch.object(deluge, '_get_auth', return_value=True), \
                mock.patch.object(deluge, 'set_torrent_label', return_value=True) as set_label:
            message, ok = deluge.check_link()
        self.assertTrue(ok)
        self.assertEqual([c.args for c in set_label.call_args_list], [(None, 'audiobooks'), (None, 'books')])
        self.assertIn('[audiobooks]', message)
