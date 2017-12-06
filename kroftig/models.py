# Kroftig backend kroftig/models.py
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

from django.db import models

import pygit2 as git


class RepoModel(models.Model):
    class Meta:
        verbose_name = 'Repository'
        verbose_name_plural = 'Repositories'

    name = models.CharField(max_length=100, unique=True, db_index=True)
    path = models.CharField(max_length=1024)
    description = models.TextField(null=True, blank=True)

    def __init__(self, *args, **kwargs):
        self._git_repo = None # lazy init
        super().__init__(*args, **kwargs)

    @property
    def git_repo(self) -> git.Repository:
        if not self._git_repo:
            self._git_repo = git.Repository(self.path)
        return self._git_repo

    @git_repo.deleter
    def git_repo(self):
        if self._git_repo:
            self._git_repo.free()
            self._git_repo = None

    def __str__(self) -> str:
        return 'RepoModel ' + str(self.name)


def get_repo_from_name(repo_name: str) -> RepoModel:
    try:
        repo = RepoModel.objects.get(name=repo_name)
    except RepoModel.DoesNotExist:
        return None
    return repo
