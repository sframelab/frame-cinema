"""Export the actual production page operations for the offline host DOM tests."""
import json
from unittest.mock import Mock, patch
from media_control import HOSTS, PREFIX, STATE, operation


def scripts():
    commands = {}
    for name in ('toggle_play', 'back_10', 'forward_10'):
        with patch('media_control.evaluate', return_value={'ok': False}) as evaluate:
            operation(Mock(), 'fixture', name)
            commands[name] = evaluate.call_args.args[2]
    return {'state': PREFIX.replace('DOMAINS', json.dumps(HOSTS)) + STATE, 'commands': commands}


if __name__ == '__main__':
    print(json.dumps(scripts()))
