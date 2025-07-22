'''
Copyright (c) 2025 Kota UCHIDA

Data repository classes. Git or KiCad's backup directory.
'''

from collections import namedtuple
import logging
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

BACKUP_DATE_PAT = re.compile(r'\d{4}-\d{2}-\d{2}_\d{6}')

GitCommitLog = namedtuple('GitCommitLog', ['hash', 'refs', 'author_name', 'author_date', 'subject', 'body'])

logger = logging.getLogger(__name__)

class Git:
    def __init__(self, kicad_proj_dir):
        self.kicad_proj_dir = kicad_proj_dir

        p = kicad_proj_dir
        self.git_root = None
        while True:
            if (p / '.git').is_dir():
                self.git_root = p
                break
            if p == p.parent:
                # '/' に到達してしまった
                break
            else:
                p = p.parent

    def extract_file(self, commit_id, file_name, dst_path):
        '''
        commit_id に含まれる file_name を dst_path へ抽出する。
        commit_id が None なら、ワーキングツリーのファイルをそのまま dst_path へコピーする。
        '''
        file_path = self.kicad_proj_dir / file_name

        if commit_id is None:
            # ワーキングツリーからファイル取得
            shutil.copy(file_path, dst_path)
            return

        rel_path = file_path.relative_to(self.git_root)
        git_show_cmd = ['git', 'show', f'{commit_id}:{rel_path}']
        res = subprocess.run(git_show_cmd, capture_output=True, cwd=self.git_root)
        with open(dst_path, 'wb') as f:
            f.write(res.stdout)
            pass

    def get_commit_logs(self):
        # コミットメッセージに現れない記号パターン（^@_@^）で区切る
        d = '^@_@^'
        git_log_cmd = ['git', 'log', '--date=iso',
                       f'--pretty=format:"#%H{d}%D{d}%an{d}%ad{d}%s{d}%b{d}"']
        res = subprocess.run(git_log_cmd, capture_output=True, cwd=self.git_root, encoding='utf-8')

        commit_logs = []
        pos = 0
        while True:
            # commit hash
            hash_pos = res.stdout.find('#', pos)
            if hash_pos < 0:
                break
            hash_pos += 1

            # hash example: 18b0278859c3d0a3aef8d3857d6fe827cfd63213
            hash_end = res.stdout.find(d, hash_pos)
            commit_hash = res.stdout[hash_pos:hash_end]
            if hash_end - hash_pos != 40:
                raise ValueError(f'hash ("{commit_hash}") length is expected to be 40')

            refs_end = res.stdout.find(d, hash_end + len(d))
            if refs_end < 0:
                raise ValueError(f'refs not found: log="{res.stdoud[hash_pos:hash_end+100]}"')
            refs = res.stdout[hash_end + len(d):refs_end]

            an_end = res.stdout.find(d, refs_end + len(d))
            if an_end < 0:
                raise ValueError(f'author name not found: log="{res.stdoud[hash_pos:hash_end+100]}"')
            an = res.stdout[refs_end + len(d):an_end]

            ad_end = res.stdout.find(d, an_end + len(d))
            if ad_end < 0:
                raise ValueError(f'author date not found: log="{res.stdoud[hash_pos:hash_end+100]}"')
            ad = res.stdout[an_end + len(d):ad_end]

            s_end = res.stdout.find(d, ad_end + len(d))
            if s_end < 0:
                raise ValueError(f'subject not found: log="{res.stdoud[hash_pos:hash_end+100]}"')
            s = res.stdout[ad_end + len(d):s_end]

            b_end = res.stdout.find(d, s_end + len(d))
            if b_end < 0:
                raise ValueError(f'body not found: log="{res.stdoud[hash_pos:hash_end+100]}"')
            b = res.stdout[s_end + len(d):b_end]

            pos = b_end + len(d)
            commit_logs.append(GitCommitLog(commit_hash, refs, an, ad, s, b))

        return commit_logs

class Backups:
    def __init__(self, kicad_proj_dir):
        self.kicad_proj_dir = kicad_proj_dir
        self.kicad_pro_path = next(kicad_proj_dir.glob('*.kicad_pro'))
        self.backups_dir = self.kicad_proj_dir / (self.kicad_pro_path.stem + '-backups')

    def extract_file(self, version, file_name, dst_path):
        '''
        version が示す zip に含まれる file_path を dst_path へ抽出する。
        version が None なら、ワーキングツリーのファイルをそのまま dst_path へコピーする。
        '''
        zip_name = f'{self.kicad_pro_path.stem}-{version}.zip'
        with zipfile.ZipFile(self.backups_dir / zip_name) as zf:
            with zf.open(file_name) as src:
                with open(dst_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)

    def get_versions(self):
        zips = self.backups_dir.glob('*.zip')
        versions = []
        for zf in zips:
            m = BACKUP_DATE_PAT.search(zf.stem)
            if not m:
                continue
            versions.append(m.group(0))
        return sorted(versions, reverse=True)

class Repo:
    def __init__(self, git_repo, backups_repo):
        self.git_repo = git_repo
        self.backups_repo = backups_repo

    def extract_file(self, version, file_name, dst_path):
        '''
        version が日付なら backups ディレクトリから、
        日付以外なら Git リポジトリからファイルを抽出する。
        '''
        logger.debug('extract_file: ver=%s file=%s dst=%s', version, file_name, dst_path)
        if dst_path.exists():
            return
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if version is None or BACKUP_DATE_PAT.match(version) is None:
            return self.git_repo.extract_file(version, file_name, dst_path)
        else:
            return self.backups_repo.extract_file(version, file_name, dst_path)
