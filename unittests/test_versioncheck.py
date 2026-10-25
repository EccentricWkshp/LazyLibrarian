#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the GitHub version checks in versioncheck.py

from unittest import mock

from lazylibrarian import versioncheck
from unittests.unittesthelpers import LLTestCase

OLD_SHA = 'a' * 40
NEW_SHA = 'b' * 40


class FakeConfig(dict):
    def get_bool(self, key):
        return bool(self.get(key))

    def get_int(self, key):
        return int(self.get(key, 0))

    def set_str(self, key, value):
        self[key] = value

    def set_int(self, key, value):
        self[key] = value


def make_config(**kwargs):
    cfg = FakeConfig(GIT_USER='EccentricWkshp', GIT_REPO='LazyLibrarian', GIT_BRANCH='master',
                     GIT_HOST='github.com', GIT_UPDATED=0, INSTALL_TYPE='source', HTTP_TIMEOUT=30,
                     SSL_VERIFY=False, SSL_CERTS='', CURRENT_VERSION=OLD_SHA, LATEST_VERSION=NEW_SHA)
    cfg.update(kwargs)
    return cfg


def make_commit(sha, message):
    return {'sha': sha, 'commit': {'message': message}}


class VersionCheckTest(LLTestCase):

    def _patch(self, cfg, response):
        return mock.patch.object(versioncheck, 'CONFIG', cfg), \
            mock.patch.object(versioncheck, 'proxy_list', return_value=None), \
            mock.patch.object(versioncheck.requests, 'get', return_value=response)

    def test_latest_version_reads_github_branch(self):
        cfg = make_config()
        response = mock.Mock(status_code=200)
        response.json.return_value = {'name': 'master', 'commit': {
            'sha': NEW_SHA, 'commit': {'committer': {'date': '2026-10-25T12:00:00Z'}}}}
        p_cfg, p_proxy, p_get = self._patch(cfg, response)
        with p_cfg, p_proxy, p_get as get:
            latest = versioncheck.get_latest_version()
        self.assertEqual(latest, NEW_SHA)
        self.assertEqual(cfg['LATEST_VERSION'], NEW_SHA)
        self.assertGreater(cfg['GIT_UPDATED'], 0, 'Z suffixed timestamp should parse')
        self.assertEqual(get.call_args.args[0],
                         'https://api.github.com/repos/EccentricWkshp/LazyLibrarian/branches/master')

    def test_latest_version_not_modified(self):
        cfg = make_config(GIT_UPDATED=1761393600)
        p_cfg, p_proxy, p_get = self._patch(cfg, mock.Mock(status_code=304))
        with p_cfg, p_proxy, p_get as get:
            latest = versioncheck.get_latest_version()
        self.assertEqual(latest, OLD_SHA)
        self.assertIn('If-Modified-Since', get.call_args.kwargs['headers'])

    def test_commit_difference_lists_titles(self):
        cfg = make_config()
        response = mock.Mock(status_code=200)
        response.json.return_value = {'status': 'ahead', 'ahead_by': 2, 'commits': [
            make_commit('c' * 40, 'First change\n\nLonger description'),
            make_commit(NEW_SHA, 'Second change'),
        ]}
        p_cfg, p_proxy, p_get = self._patch(cfg, response)
        with p_cfg, p_proxy, p_get as get:
            commits, commit_list = versioncheck.get_commit_difference_from_git()
        self.assertEqual(commits, 2)
        self.assertEqual(commit_list, 'Second change\nFirst change\n')
        self.assertEqual(get.call_args.args[0],
                         f'https://api.github.com/repos/EccentricWkshp/LazyLibrarian/compare/{OLD_SHA}...{NEW_SHA}')

    def test_commit_difference_uses_ahead_by_over_truncated_list(self):
        cfg = make_config()
        response = mock.Mock(status_code=200)
        response.json.return_value = {'status': 'ahead', 'ahead_by': 300,
                                      'commits': [make_commit(NEW_SHA, 'Latest')]}
        p_cfg, p_proxy, p_get = self._patch(cfg, response)
        with p_cfg, p_proxy, p_get:
            commits, _ = versioncheck.get_commit_difference_from_git()
        self.assertEqual(commits, 300)

    def test_commit_difference_unavailable_latest_compares_branch(self):
        cfg = make_config(LATEST_VERSION='Not_Available_From_Git : 500 : url')
        response = mock.Mock(status_code=200)
        response.json.return_value = {'status': 'ahead', 'ahead_by': 1,
                                      'commits': [make_commit(NEW_SHA, 'Latest')]}
        p_cfg, p_proxy, p_get = self._patch(cfg, response)
        with p_cfg, p_proxy, p_get as get:
            commits, _ = versioncheck.get_commit_difference_from_git()
        self.assertEqual(commits, 1)
        self.assertTrue(get.call_args.args[0].endswith(f'/compare/{OLD_SHA}...master'))
        self.assertEqual(cfg['LATEST_VERSION'], NEW_SHA)

    def test_commit_difference_unknown_hash(self):
        cfg = make_config()
        response = mock.Mock(status_code=404)
        response.json.return_value = {'message': 'Not Found'}
        p_cfg, p_proxy, p_get = self._patch(cfg, response)
        with p_cfg, p_proxy, p_get:
            commits, commit_list = versioncheck.get_commit_difference_from_git()
        self.assertEqual(commits, -1)
        self.assertIn('Unknown version', commit_list)
