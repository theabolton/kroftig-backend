# Kroftig backend kroftig/git_utils.py
#
# Copyright © 2017 Sean Bolton.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import os

import pygit2 as git


def _read_tree_inner(repo, gittree, filter_path, tree_dict, path_prefix):
    """Inner recursive function for _read_tree()."""
    for entry in gittree:
        path = os.path.join(path_prefix, entry.name)
        if filter_path and (filter_path == path or filter_path.startswith(path + '/')):
            if entry.type == 'tree':
                subtree = repo.get(entry.oid)
                _read_tree_inner(repo, subtree, filter_path, tree_dict, path)
        elif not filter_path or path.startswith(filter_path + '/'):
            tree_dict[path] = { 'oid': entry.oid }

def _read_tree(repo, commit, filter_path):
    """Recursively read the trees of `commit`, and return a dict containing only those files in the
    commit which are part of the tree with path `filter_path`.
    """
    tree_dict = {}
    _read_tree_inner(repo, commit.tree, filter_path, tree_dict, '')
    return tree_dict

def get_latest_changing_commits_for_tree(repo: git.Repository, root: git.Commit, filter_path: str):
    """Get the 'latest changing commit' for each file in the tree with path `filter_path` in the
    commit `root`, like GitHub does in their tree view. While this intuitively is the 'most recent
    commit to change the file', it is actually the oldest ancestor commit above `root` such that all
    commits between it and `root` inclusive point to the same blob.

    Return a compound dict of the form:

    {
      'file1': { 'oid': '<file-blob-sha-in-hex>', 'latest': '<ancestor-commit-sha-in-hex>' },
      'path/file2': { 'oid': '<file-blob-sha-in-hex>', 'latest': '<ancestor-commit-sha-in-hex>' },
    }
    """
    commit = root
    commits = {}
    resolved = []
    tree = _read_tree(repo, root, filter_path)
    for path in tree:
        tree[path]['latest'] = commit
    commits[commit.hex] = { 'tree': tree, 'held': {**tree} }
    pending_commits = set((commit.hex, ))

    while pending_commits:
        commit = repo.get(pending_commits.pop())
        working = commits[commit.hex]['held']
        commits[commit.hex]['held'] = {}

        for (path, path_dict) in working.items():
            assert 'oid' in path_dict
            assert 'latest' in path_dict
            found = False
            for parent_commit in commit.parents:
                if parent_commit.hex not in commits:
                    parent_tree = _read_tree(repo, parent_commit, filter_path)
                    commits[parent_commit.hex] = { 'tree': parent_tree, 'held': {} }
                else:
                    parent_tree = commits[parent_commit.hex]['tree']
                assert isinstance(parent_tree, dict)
                parent_path_dict = parent_tree.get(path, None)
                if parent_path_dict and parent_path_dict['oid'] == path_dict['oid']:
                    found = True
                    path_dict['latest'] = parent_commit
                    commits[parent_commit.hex]['held'][path] = path_dict
                    pending_commits.add(parent_commit.hex)
                    break
            if not found:
                resolved.append((path, path_dict))

    #resolved.sort(key=lambda t: t[0])
    #for (path, path_dict) in resolved:
    #    print(path, path_dict['latest'].message.splitlines()[0])
    return dict(resolved)
