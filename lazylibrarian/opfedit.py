#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

#  basic opf editor, only edit "our" fields, leave everything else unchanged

import logging
import os
from xml.sax.saxutils import escape, unescape

# values are read unescaped and written escaped again, quotes too as some go in attributes
ENTITIES = {'&quot;': '"', '&apos;': "'"}
QUOTES = {'"': '&quot;'}


def opf_read(filename):
    """ The opf as a template with a $$token$$ for each of our fields and the fields' values, ('', [])
        if it can't be read, so a template that stops part way through is never written back """
    logger = logging.getLogger(__name__)
    matchlogger = logging.getLogger('special.matching')
    if not os.path.exists(filename):
        return '', []
    keys = ['<dc:title>', '<dc:language>', '<dc:publisher>', '<dc:date>']
    subject = '<dc:subject>'
    scheme = '<dc:identifier'
    creator = '<dc:creator'
    content = '<meta content="'
    description = '<dc:description>'
    enddesc = description.replace('<', '</')
    desc = ''
    subjects = 0
    creators = 0
    replaces = []
    outfile = f"{filename}_mod"
    try:
        with open(filename, encoding='utf-8') as i:
            data = i.readlines()
    except (OSError, UnicodeDecodeError) as e:
        logger.debug(f"Can't read {filename}: {type(e).__name__} {e}")
        return '', []
    with open(outfile, 'w', encoding='utf-8') as f:
        try:
            for lyne in data:
                if description in lyne:
                    desc = lyne
                elif desc:
                    desc += lyne
                if enddesc in lyne:
                    new_lyne, token, value = extract_key(description, desc)
                    replaces.append((token, value))
                    f.write(new_lyne)
                    desc = ''
                elif not desc:
                    new_lyne = ''
                    for key in keys:
                        if key in lyne:
                            new_lyne, token, value = extract_key(key, lyne)
                            replaces.append((token, value))
                            break

                    if subject in lyne:
                        new_lyne, token, value = extract_key(subject, lyne)
                        indexed = f"subject_{subjects:02d}"
                        subjects += 1
                        new_lyne = new_lyne.replace('$$subject$$', f'$${indexed}$$')
                        replaces.append((indexed, value))

                    if scheme in lyne:
                        new_lyne, token, value = extract_scheme(lyne)
                        if token:
                            replaces.append((token, value))

                    if creator in lyne:
                        indexed = f"_{creators:02d}"
                        # the first creator's is plain fileas, each one has its own
                        fileas_token = f"fileas{indexed}" if creators else 'fileas'
                        creators += 1
                        new_lyne, role, fileas, value = extract_creator(lyne)
                        replaces.append((f"role{indexed}", role))
                        replaces.append((f"creator{indexed}", value))
                        replaces.append((fileas_token, fileas))
                        new_lyne = new_lyne.replace('$$role$$', f'$$role{indexed}$$').replace(
                            '$$creator$$', f'$$creator{indexed}$$').replace('$$fileas$$', f'$${fileas_token}$$')

                    if content in lyne:
                        new_lyne, token, value = extract_content(content, lyne)
                        replaces.append((token, value))

                    if not new_lyne:
                        new_lyne = lyne
                    f.write(new_lyne)
            if desc:
                raise ValueError(f"{description} isn't closed")
        except Exception as e:
            logger.debug(f"Can't read {filename}: {type(e).__name__} {e}")
            replaces = None
    if replaces is None:
        os.remove(outfile)
        return '', []
    matchlogger.debug(','.join(item[0] for item in replaces))
    return outfile, [(token, unescape(value, ENTITIES)) for token, value in replaces]


def extract_key(key, data):
    ident = key.split(':', 1)[1].split('>')[0]
    endkey = key.replace('<', '</')
    value = data.split(key, 1)[1].split(endkey, 1)[0]
    return data.replace(key + value + endkey, f"{key}$${ident}$${endkey}"), ident, value


def extract_scheme(data):
    """ An identifier with a scheme, the line unchanged and no token for one without (epub3 style) """
    if 'scheme="' not in data:
        return data, '', ''
    ident = data.split('scheme="', 1)[1].split('"')[0]
    value = data.split('>', 1)[1].split('<')[0]
    return data.replace(f">{value}<", f'>$${ident}$$<'), ident, value


def extract_content(key, data):
    ident = data.split('name="', 1)[1].split('"')[0]
    value = data.split(key, 1)[1].split('"')[0]
    return data.replace(f"{key + value}\"", f"{key}$${ident}$$\""), ident, value


def extract_creator(data):
    """ The creator's name, and its role and file-as when it has them, which epub3 doesn't """
    def attribute(name):
        return data.split(f'{name}="', 1)[1].split('"')[0] if f'{name}="' in data else ''
    fileas = attribute('file-as')
    role = attribute('role')
    value = data.split('>', 1)[1].split('<')[0]
    new_lyne = data.replace(f">{value}<", '>$$creator$$<')
    if 'role="' in data:
        new_lyne = new_lyne.replace(f"role=\"{role}\"", 'role="$$role$$"')
    if 'file-as="' in data:
        new_lyne = new_lyne.replace(f"file-as=\"{fileas}\"", 'file-as="$$fileas$$"')
    return new_lyne, role, fileas, value


def opf_write(filename, replaces):
    if not os.path.exists(filename):
        return ''
    with open(filename, encoding='utf-8') as i:
        data = i.readlines()
        outfile = f"{filename}_mod"
        with open(outfile, 'w', encoding='utf-8') as f:
            for lyne in data:
                for item in replaces:
                    lyne = lyne.replace(f'$${item[0]}$$', escape(item[1], QUOTES))
                f.write(lyne)
    return outfile
