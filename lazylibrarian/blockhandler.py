#  This file is part of Lazylibrarian.
#
# Purpose:
#   Handle blocking behaviour, keep track of blocked providers, etc

import logging
import time

from lazylibrarian.configtypes import ConfigDict
from lazylibrarian.formatter import plural, pretty_approx_time, today


class BlockHandler:
    # Seconds a provider is blocked for when it keeps answering "too many requests",
    # escalating each time it is limited again soon after the previous block expired
    RATE_LIMIT_LADDER = (30, 120, 600, 3600)

    def __init__(self):
        self._nab_apicount_day: str = today()
        self._provider_list: dict[str, dict] = {}  # {name: {resume, reason}} = {}
        self._backoff: dict[str, dict] = {}  # {name: {level, when}} for block_provider_backoff
        self._gb_calls: int = 0
        self._config: ConfigDict | None = None
        self._newznab: ConfigDict | None = None
        self._torznab: ConfigDict | None = None

    def set_config(self, config: ConfigDict, newznab: ConfigDict, torznab: ConfigDict):
        """ Set the configuration used for the BlockHandler. By providing them in this form,
        this module does not need to import config2, which would cause a circular dependency.
        Args:
        config: The base configuration
        newznab, torznab: The (array!) configs for these provider types, needed here to be able to
        handle the counting of API calls. We cannot import arrayconfig, hence just import as a ConfigDict.
        """
        self._config = config  # So we don't need to import config2
        self._newznab = newznab
        self._torznab = torznab

    def _find_key(self, name: str) -> str:
        """ Return existing matching key in _provider_list (case-insensitive) or name """
        if name in self._provider_list:
            return name
        name_lower = name.lower()
        for k in self._provider_list:
            if k.lower() == name_lower:
                return k
        return name

    def remove_provider_entry(self, name: str) -> None:
        key = self._find_key(name)
        self._provider_list.pop(key, None)

    def add_provider_entry(self, name: str, delay: int, reason: str) -> None:
        key = self._find_key(name)
        self._provider_list[key] = {"resume": int(time.time()) + delay, "reason": reason}

    def replace_provider_entry(self, name: str, delay: int, reason: str) -> None:
        new_resume = int(time.time()) + delay
        key = self._find_key(name)
        existing = self._provider_list.get(key)
        if existing and existing.get("resume", 0) > new_resume:
            return
        self._provider_list[key] = {"resume": new_resume, "reason": reason}

    def block_provider(self, who: str, why: str, delay: int | None = None) -> int:
        """ Block provider 'who' for reason 'why'. Returns number of seconds block will last """
        logger = logging.getLogger(__name__)
        if delay is None:
            delay = self._config.get_int('BLOCKLIST_TIMER') if self._config is not None else 3600

        if delay == 0:
            logger.debug(f'Not blocking {who},{why} as timer is zero')
            return 0

        if len(why) > 80:
            why = why[:80]

        timestr = pretty_approx_time(delay)
        logger.info(f"Blocking provider {who} for {timestr} because {why}")
        self.replace_provider_entry(who, delay, why)
        logger.debug(
            f"Provider Blocklist contains {len(self._provider_list)} {plural(len(self._provider_list), 'entry')}")
        return delay

    def block_provider_backoff(self, who: str, why: str) -> int:
        """ Block provider 'who' with a delay that escalates each time it rate-limits us again shortly
        after its previous block expired (see RATE_LIMIT_LADDER). A provider that is down, or that has been
        disabled upstream (eg by Prowlarr), is then asked less and less often instead of every 30 seconds.
        A quiet spell of more than one further delay, or reset_backoff(), starts again at the shortest delay.
        Returns the number of seconds the provider is blocked for. """
        now = time.time()
        previous = self._backoff.get(who)
        if self.is_blocked(who):
            # searches already in flight can all be rate-limited together: that is a single event
            if previous:
                return max(0, int(previous['when'] + self.RATE_LIMIT_LADDER[previous['level']] - now))
            return 0

        ladder = self.RATE_LIMIT_LADDER
        level = 0
        if previous and now - previous['when'] < ladder[previous['level']] * 2:
            level = min(previous['level'] + 1, len(ladder) - 1)
        self._backoff[who] = {'level': level, 'when': now}
        return self.block_provider(who, why, delay=ladder[level])

    def reset_backoff(self, who: str) -> None:
        """ The provider answered normally, so forget any escalation of its rate-limit delay """
        self._backoff.pop(who, None)

    def number_blocked(self) -> int:
        """ Number of blocked providers """
        return len(self._provider_list)

    def clear_all(self) -> int:
        """ Clear all blocks, returning how many were on the list """
        num = self.number_blocked()
        self._provider_list.clear()
        self._backoff.clear()
        return num

    def check_day(self, pretend_day: str | None = None) -> bool:
        """ Reset api counters if it's a new day since last check. Returns True if values are reset.
         The pretend_day argument is used for testing. """
        daystr = pretend_day if pretend_day else today()
        if self._nab_apicount_day != daystr:
            self._nab_apicount_day = daystr
            if self._newznab:
                for provider in self._newznab:
                    provider.set_int('APICOUNT', 0)
            if self._torznab:
                for provider in self._torznab:
                    provider.set_int('APICOUNT', 0)
            return True
        return False

    def is_blocked(self, name: str) -> bool:
        """ Returns true if the provider is blocked """
        self.check_day()

        timenow = int(time.time())
        key = self._find_key(name)
        if key in self._provider_list:
            entry = self._provider_list[key]
            if timenow < int(entry['resume']):
                return True
            self._provider_list.pop(key, None)
        return False

    def get_text_list_of_blocks(self) -> str:
        result = ''
        for key, line in self._provider_list.items():
            resume = int(line['resume']) - int(time.time())
            if resume > 0:
                time_str = pretty_approx_time(resume)
                new_entry = f"{key} blocked for {time_str}: {line['reason']}\n"
                result += new_entry

        if result == '':
            result = 'No blocked providers'
        return result


# Global blockhandler object

BLOCKHANDLER = BlockHandler()
