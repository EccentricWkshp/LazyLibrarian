#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the /api/v1 models' base (apiv1/models.py): camelCase names, and a column the database left
#   NULL given where a value is needed

import unittest

from lazylibrarian.apiv1.models import ApiModel


class Item(ApiModel):
    audio_status: str
    pages: int = 0
    rating: float = 0
    read: bool = False
    note: str | None = None


class ApiModelTest(unittest.TestCase):

    def test_null_is_empty_where_a_value_is_needed(self):
        item = Item.model_validate({'audio_status': None, 'pages': None, 'rating': None, 'read': None, 'note': None})
        self.assertEqual(item.model_dump(by_alias=True),
                         {'audioStatus': '', 'pages': 0, 'rating': 0.0, 'read': False, 'note': None},
                         'A field that can be empty stays empty')

    def test_camel_case(self):
        self.assertEqual(Item.model_validate({'audioStatus': 'Wanted'}).audio_status, 'Wanted')


if __name__ == '__main__':
    unittest.main()
