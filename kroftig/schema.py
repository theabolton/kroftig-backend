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

import datetime

import django.contrib.humanize.templatetags.humanize as humanize
import graphene
from graphene import ObjectType, relay
from graphene.relay import Node
from graphene_django import DjangoObjectType
import pygit2 as git

from .models import get_repo_from_name, RepoModel


def get_current_branch(git_repo: git.Repository) -> str:
    try:
        #branch = git_repo.lookup_reference('HEAD').resolve().shorthand
        branch = git_repo.head.shorthand
    except KeyError:
        branch = '<unknown branch (empty repo?)>'
    return branch


def humantime(time: int) -> str:
    """Convert seconds-since-epoch to e.g. '1 day ago'."""
    return humanize.naturaltime(datetime.datetime.fromtimestamp(time))


class Branch(ObjectType):
    class Meta:
        interfaces = (Node, )

    name = graphene.String()
    message = graphene.String()
    rev = graphene.String()
    ctime = graphene.String()

    @classmethod
    def get_node(cls, info, id):
        """Node IDs for Branchs are of the form (before base64 encoding):
        'Branch:<repo_name>^<commit-sha-in-hex>'.
        """
        (repo_name, branch_name) = id.split('^')
        repo = get_repo_from_name(repo_name)
        if not repo:
            return None
        git_repo = repo.git_repo
        if branch_name not in git_repo.branches.local:
            return None
        commit = git_repo.revparse_single(branch_name)
        if not commit:
            return None
        return Branch(id=id, name=branch_name, message=commit.message, rev=commit.hex,
                      ctime=humantime(commit.committer.time))


class BranchConnection(relay.Connection):
    class Meta:
        node = Branch

    def resolve_repo_branches(repo: RepoModel, info, **args):
        """Resolver for Repo field 'branches'."""
        git_repo = repo.git_repo
        branches = []
        for branch_name in git_repo.branches.local:
            commit = repo.git_repo.revparse_single(branch_name)
            branches.append(Branch(id=str(repo.name) + '^' + branch_name, name=branch_name,
                                   message=commit.message, rev=commit.hex,
                                   ctime=humantime(commit.committer.time)))
        return branches


class LogCommit(ObjectType):
    class Meta:
        interfaces = (Node, )

    oid = graphene.String()
    message = graphene.String()
    author = graphene.String()
    committer = graphene.String()
    atime = graphene.String()
    #ctime = graphene.String()

    @classmethod
    def get_node(cls, info, id):
        """Node IDs for LogCommits are of the form (before base64 encoding):
        'LogCommit:<repo_name>^<commit-sha-in-hex>'.
        """
        (repo_name, commit_id) = id.split('^')
        repo = get_repo_from_name(repo_name)
        if not repo:
            return None
        commit = repo.git_repo.get(commit_id)
        if not commit:
            return None
        return LogCommit(id=id, oid=commit_id, message=commit.message, author=commit.author.name,
                         committer=commit.committer.name, atime=humantime(commit.commit_time))


class LogCommitConnection(relay.Connection):
    class Meta:
        node = LogCommit

    rev = graphene.String()

    def resolve_rev(connection: 'LogCommitConnection', info, **args):
        if info.context.kroftig:
            return info.context.kroftig.get('rev', None)
        return None

    @staticmethod
    def get_repo_commits_input_fields():
        """Input fields for Repo field 'commits'."""
        return {
            'rev': graphene.Argument(graphene.String),
        }

    def resolve_repo_commits(repo: RepoModel, info, **args):
        """Resolver for Repo field 'commits'."""
        git_repo = repo.git_repo
        rev = args.get('rev', None)
        if not rev:
            last = git_repo[git_repo.head.target]
        else:
            last = git_repo.revparse_single(rev)
            if not last:
                return None
            info.context.kroftig['rev'] = rev
        commits = []
        for commit in git_repo.walk(last.id, git.GIT_SORT_TOPOLOGICAL):
            obj = LogCommit(id=str(repo.name) + '^' + commit.hex, oid=commit.hex,
                            message=commit.message,
                            author=commit.author.name, committer=commit.committer.name,
                            atime=humantime(commit.commit_time))
            commits.append(obj)
        return commits


class Repo(DjangoObjectType):
    class Meta:
        model = RepoModel
        interfaces = (Node, )

    current_branch = graphene.String()
    branches = relay.ConnectionField(
        BranchConnection,
        resolver=BranchConnection.resolve_repo_branches,
        #**BranchConnection.get_repo_commits_input_fields()
    )
    commits = relay.ConnectionField(
        LogCommitConnection,
        resolver=LogCommitConnection.resolve_repo_commits,
        **LogCommitConnection.get_repo_commits_input_fields()
    )

    def resolve_current_branch(repo: RepoModel, info):
        git_repo = repo.git_repo
        branch = get_current_branch(git_repo)
        return branch

    @staticmethod
    def get_query_repo_input_fields():
        """Input fields for Query field 'repo'."""
        return {
            'name': graphene.Argument(graphene.String, required=True),
        }

    def resolve_query_repo(_, info, **args):
        """Resolver for Query field 'repo'."""
        name = args.get('name')
        repo = get_repo_from_name(name)
        info.context.kroftig = { 'repo': repo }
        return repo


class Query(object):
    node = Node.Field()
    repo = graphene.Field(
        Repo,
        resolver=Repo.resolve_query_repo,
        **Repo.get_query_repo_input_fields()
    )
    repos = graphene.List(Repo)

    def resolve_repos(_, info):
        return RepoModel.objects.all().order_by('name')
