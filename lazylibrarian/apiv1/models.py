#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

""" Base for the API's request and response models """

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator
from pydantic.alias_generators import to_camel

# what a field that has to have a value is when the database has none (NULL)
EMPTY = {str: '', int: 0, float: 0.0, bool: False}


class ApiModel(BaseModel):
    """ snake_case in Python, camelCase in JSON like Sonarr's API. Built from the services'
    snake_case dicts """
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, validate_by_alias=True)

    @field_validator('*', mode='before')
    @classmethod
    def _none_is_empty(cls, value, info: ValidationInfo):
        """ A column the old database left NULL is empty text, or 0, where a value is needed """
        if value is None and info.field_name:
            return EMPTY.get(cls.model_fields[info.field_name].annotation, value)
        return value
