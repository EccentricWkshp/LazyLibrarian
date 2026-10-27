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

""" Language identification without numpy: langid.py's classifier (Marco Lui, BSD licence, see
data/langid/LICENSE) and its trained model, in plain Python. It gives what langid gives. langid
needs numpy, the largest thing LazyLibrarian installed, for a few array sums.

The model is data/langid/model.bin, langid 1.1.6's, as arrays rather than a pickle: bz2 of a 4
byte little-endian length, that much JSON (the languages, their prior log-probabilities, the
number of features and the tokenizer's output table), then the feature log-probabilities as
little-endian float32, features by languages, and the tokenizer's state table as little-endian
uint16 """

import bz2
import json
import math
import os
import struct
import sys
from array import array
from collections import defaultdict

MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'langid', 'model.bin')


class LanguageIdentifier:
    """ langid's LanguageIdentifier: classify(text) is (language, probability) """

    def __init__(self, classes, nb_pc, nb_ptc, features, nextmove, output):
        self._all = (classes, nb_pc)
        self.nb_ptc = nb_ptc
        self.features = features
        self.nextmove = nextmove
        self.output = output
        self.set_languages(None)

    @classmethod
    def load(cls, path: str = MODEL) -> 'LanguageIdentifier':
        with open(path, 'rb') as f:
            data = bz2.decompress(f.read())
        size = struct.unpack_from('<I', data)[0]
        header = json.loads(data[4:4 + size])
        classes, features = header['classes'], header['features']
        nb_ptc = array('f')
        start = 4 + size
        nb_ptc.frombytes(data[start:start + 4 * features * len(classes)])
        nextmove = array('H')
        nextmove.frombytes(data[start + 4 * features * len(classes):])
        if sys.byteorder != 'little':
            nb_ptc.byteswap()
            nextmove.byteswap()
        output = {int(state): indexes for state, indexes in header['output'].items()}
        return cls(classes, header['nb_pc'], nb_ptc, features, nextmove, output)

    def set_languages(self, langs=None):
        """ Only choose between these languages, or all of them for None """
        classes, nb_pc = self._all
        if langs is None:
            self.columns = list(range(len(classes)))
        else:
            unknown = [lang for lang in langs if lang not in classes]
            if unknown:
                raise ValueError(f"Unknown language code {unknown[0]}")
            self.columns = [i for i, lang in enumerate(classes) if lang in langs]
        self.classes = [classes[i] for i in self.columns]
        self.nb_pc = [nb_pc[i] for i in self.columns]

    def instance2fv(self, text) -> dict[int, int]:
        """ The features of a text and how often each occurs, from the tokenizer's state machine """
        if isinstance(text, str):
            text = text.encode('utf8')
        state = 0
        statecount = defaultdict(int)
        for letter in text:
            state = self.nextmove[(state << 8) + letter]
            statecount[state] += 1
        counts = defaultdict(int)
        for state, count in statecount.items():
            for index in self.output.get(state, ()):
                counts[index] += count
        return counts

    def classify(self, text) -> tuple[str, float]:
        """ The likeliest language and its probability among the languages chosen """
        counts = self.instance2fv(text)
        width = len(self._all[0])
        scores = list(self.nb_pc)
        for index, count in counts.items():
            row = index * width
            for position, column in enumerate(self.columns):
                scores[position] += count * self.nb_ptc[row + column]
        # langid normalises the log-probabilities as 1/sum(exp(pd_j - pd_i)), a softmax
        top = max(scores)
        weights = [math.exp(score - top) for score in scores]
        best = max(range(len(scores)), key=scores.__getitem__)
        return str(self.classes[best]), weights[best] / sum(weights)
