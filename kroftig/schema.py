# Kroftig backend kroftig/schema.py
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

import graphene
from graphene import ObjectType, relay
from graphene.relay import Node
import pygit2 as git


def get_current_branch(repo):
    try:
        #branch = repo.lookup_reference('HEAD').resolve().shorthand
        branch = repo.head.shorthand
    except KeyError:
        branch = '<unknown branch (empty repo?)>'
    return branch


class LogCommit(ObjectType):
    class Meta:
        interfaces = (Node, )

    oid = graphene.String()
    message = graphene.String()


class LogCommitConnection(relay.Connection):
    class Meta:
        node = LogCommit

    def resolve_repo_commits(repo, info, **args):
        last = repo[repo.head.target]
        commits = []
        for commit in repo.walk(last.id, git.GIT_SORT_TOPOLOGICAL):
            obj = LogCommit(id=commit.hex, oid=commit.hex, message=commit.message)
            commits.append(obj)
        return commits


class Repo(ObjectType):
    class Meta:
        interfaces = (Node, )

    branch = graphene.String()
    commits = relay.ConnectionField(
        LogCommitConnection,
        resolver=LogCommitConnection.resolve_repo_commits,
        #**LogCommitConnection.get_repo_commits_input_fields()
    )

    def resolve_branch(repo, info):
        branch = get_current_branch(repo)
        return branch

    def resolve_query_repo(_, info):
        """Resolver for Query field 'repo'."""
        path = os.getcwd() # -FIX-
        repo = git.Repository(path)
        return repo


class Query(object):
    node = Node.Field()
    repo = graphene.Field(
        Repo,
        resolver=Repo.resolve_query_repo,
        #**Repo.get_query_repo_input_fields()
    )
