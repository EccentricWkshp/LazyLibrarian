#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the helpers in web/common.py

import unittest

import cherrypy

from lazylibrarian.web.common import BasePages


class ValidateParamTest(unittest.TestCase):

    def test_allowed_values(self):
        self.assertTrue(BasePages.validate_param('name', 'Anne Rice', ['<', '>'], 404))
        self.assertTrue(BasePages.validate_param('name', '', ['<', '>'], 404))

    def test_rejected_value_without_an_error_page(self):
        self.assertFalse(BasePages.validate_param('name', 'a%3Cscript', ['<', '>'], None))

    def test_rejected_value_with_an_error_page(self):
        with self.assertRaises(cherrypy.HTTPError) as cm:
            BasePages.validate_param('name', '<script>', ['<', '>'], 404)
        self.assertEqual(cm.exception.status, 404)


if __name__ == '__main__':
    unittest.main()
