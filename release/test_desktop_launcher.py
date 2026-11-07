"""The double-click launcher ("Install Frame Cinema.desktop") finds its installer.

Parses Exec the way the Desktop Entry spec says (string escapes, then quoting),
then runs it with sh in a download folder.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_public  # noqa: E402


def exec_argv(entry, launcher):
    line = next(l for l in entry.splitlines() if l.startswith('Exec='))[5:]
    line = line.replace('\\\\', '\\')  # string-level escape
    argv, word, quoted, i = [], '', False, 0
    while i < len(line):
        c = line[i]
        if quoted and c == '\\' and line[i + 1] in '"`$\\':
            word += line[i + 1]
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        elif c == ' ' and not quoted:
            if word:
                argv.append(word)
            word = ''
        else:
            word += c
        i += 1
    argv.append(word)
    return [str(launcher) if a == '%k' else a for a in argv]


@unittest.skipUnless(os.name == 'posix', 'runs the launcher with sh')
class DesktopLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name) / 'build'
        self.build.mkdir()
        self.single = self.build / 'FrameCinema-0.5.16-installer.sh'
        self.single.write_text('echo ran "$0"\n')
        launcher = build_public.desktop_launcher(self.single, '0.5.16', self.build)
        self.entry = launcher.read_text()
        self.downloads = Path(self.temp.name) / 'My Downloads'
        self.downloads.mkdir()
        self.launcher = self.downloads / launcher.name
        self.launcher.write_text(self.entry)

    def run_launcher(self):
        env = dict(os.environ, PATH='/usr/bin:/bin')  # no kdialog here
        return subprocess.run(exec_argv(self.entry, self.launcher), capture_output=True, text=True, env=env, timeout=20)

    def test_runs_the_installer_beside_it(self):
        (self.downloads / self.single.name).write_text('echo ran "$0"\n')
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ran ' + str(self.downloads / self.single.name), result.stdout)

    def test_runs_a_renamed_second_download(self):
        renamed = self.downloads / 'FrameCinema-0.5.16-installer (1).sh'
        renamed.write_text('echo ran "$0"\n')
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ran ' + str(renamed), result.stdout)

    def test_refuses_a_different_file_with_the_installer_name(self):
        (self.downloads / self.single.name).write_text('echo other "$0"\n')
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('other', result.stdout)

    def test_never_runs_another_version(self):
        (self.downloads / 'FrameCinema-0.5.15-installer.sh').write_text('echo ran "$0"\n')
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('ran', result.stdout)

    def test_fails_cleanly_without_an_installer(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('ran', result.stdout)

    def test_exec_has_no_unescaped_field_codes(self):
        line = next(l for l in self.entry.splitlines() if l.startswith('Exec='))
        self.assertEqual(line.count('%'), 1)
        self.assertTrue(line.endswith(' %k'))


if __name__ == '__main__':
    unittest.main()
