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


def cache_in_context(context, key, value):
    """Save a key-value pair in the context for use by child resolvers."""
    if hasattr(context, 'kroftig'):
        context.kroftig[key] = value
    else:
        context.kroftig = { key: value }


def get_from_context_cache(context, key):
    """Retrieve a cached item from the context. Raise KeyError if not present."""
    return context.kroftig[key]


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


class TreeEntry(ObjectType):
    class Meta:
        interfaces = (Node, )

    oid = graphene.String()
    name = graphene.String()
    filemode = graphene.Int()
    type_ = graphene.String(name='type')
    size = graphene.Int()

    def resolve_size(entry: 'TreeEntry', info, **args):
        repo = get_from_context_cache(info.context, 'repo')
        obj = repo.git_repo.get(entry.oid)
        if obj.type == git.GIT_OBJ_BLOB:
            return obj.size
        return None

    @classmethod
    def get_node(cls, info, id):
        """Sigh. PyGit2 doesn't include git_tree_lookup(), so until I can put together a PR for it,
        just include the tree id in the encoded Node ID, like this (before base64 encoding):
        'TreeEntry:<repo_name>^<tree-sha-in-hex>^<entry-sha-in-hex>'.
        """
        # https://libgit2.github.com/libgit2/#HEAD/group/tree/git_tree_lookup
        (repo_name, tree_id, entry_id) = id.split('^')
        repo = get_repo_from_name(repo_name)
        if not repo:
            return None
        cache_in_context(info.context, 'repo', repo)
        git_repo = repo.git_repo
        tree = git_repo.get(tree_id)
        if not tree:
            return None
        # And no get_tree_entry_byid() either? Fine, do it manually:
        # https://libgit2.github.com/libgit2/#HEAD/group/tree/git_tree_entry_byid
        entry = None
        for e in tree:
            if e.hex == entry_id:
                entry = e
                break
        if not entry:
            return None
        return TreeEntry(id=id, oid=entry.hex, name=entry.name, filemode=entry.filemode,
                         type_=entry.type)


class Tree(relay.Connection):
    class Meta:
        node = TreeEntry

    @staticmethod
    def build_instance(repo_name, commit):
        entries = []
        for entry in commit.tree:
            entries.append(TreeEntry(id=repo_name + '^' + commit.tree.hex + '^' + entry.hex,
                                     oid=entry.hex, name=entry.name, filemode=entry.filemode,
                                     type_=entry.type))
        return entries

    def resolve_full_commit_tree(commit: 'FullCommit', info, **args):
        """Resolver for FullCommit field 'tree'."""
        repo = get_from_context_cache(info.context, 'repo')
        git_repo = repo.git_repo
        commit = git_repo.get(commit.oid)
        return Tree.build_instance(repo.name, commit)

    @staticmethod
    def get_repo_tree_input_fields():
        """Input fields for Repo field 'tree'."""
        return {
            'rev': graphene.Argument(graphene.String),
        }

    def resolve_repo_tree(repo: RepoModel, info, **args):
        """Resolver for Repo field 'tree'."""
        git_repo = repo.git_repo
        rev = args.get('rev')
        try:
            commit = git_repo.revparse_single(rev)
        except KeyError:
            raise Exception("revision '{}' not found".format(rev))
        return Tree.build_instance(repo.name, commit)


class FullCommit(ObjectType):
    class Meta:
        interfaces = (Node, )

    oid = graphene.String()
    message = graphene.String()
    author = graphene.String()
    author_time = graphene.String()
    author_email = graphene.String()
    committer = graphene.String()
    committer_time = graphene.String()
    committer_email = graphene.String()
    # The front end will often want full commit info along with the top level tree of the commit, so
    # make a Tree instance available. On the other hand, parent commits won't be fetched for the
    # same view, so just return their IDs.
    parent_ids = graphene.List(graphene.String)
    tree = relay.ConnectionField(Tree, resolver=Tree.resolve_full_commit_tree,
                                 description="Relatively expensive, only fetch if needed")

    @staticmethod
    def build_instance(id, commit):
        if not commit:
            return None
        return FullCommit(id=id, oid=commit.hex, message=commit.message,
                          author=commit.author.name, author_time=humantime(commit.author.time),
                          author_email=commit.author.email,
                          committer=commit.committer.name,
                          committer_time=humantime(commit.committer.time),
                          committer_email=commit.committer.email,
                          parent_ids=commit.parent_ids)

    @classmethod
    def get_node(cls, info, id):
        """Node IDs for FullCommits are of the form (before base64 encoding):
        'FullCommit:<repo_name>^<commit-sha-in-hex>'.
        """
        (repo_name, commit_id) = id.split('^')
        repo = get_repo_from_name(repo_name)
        if not repo:
            return None
        cache_in_context(info.context, 'repo', repo)
        git_repo = repo.git_repo
        return cls.build_instance(id, git_repo.get(commit_id))

    @staticmethod
    def get_repo_commit_input_fields():
        """Input fields for Repo field 'commit'."""
        return {
            'rev': graphene.Argument(graphene.String, required=True),
        }

    def resolve_repo_commit(repo: RepoModel, info, **args):
        """Resolver for Repo field 'commit'."""
        git_repo = repo.git_repo
        rev = args.get('rev', None)
        if not rev:
            return None
        commit = git_repo.revparse_single(rev)
        return FullCommit.build_instance(repo.name + '^' + commit.hex, commit)


class LogCommitConnection(relay.Connection):
    class Meta:
        node = LogCommit

    rev = graphene.String()

    def resolve_rev(connection: 'LogCommitConnection', info, **args):
        return get_from_context_cache(info.context, 'rev')

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
        # stash rev for resolve_rev()
        cache_in_context(info.context, 'rev', rev)
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
    commit = graphene.Field(
        FullCommit,
        resolver=FullCommit.resolve_repo_commit,
        **FullCommit.get_repo_commit_input_fields()
    )
    commits = relay.ConnectionField(
        LogCommitConnection,
        resolver=LogCommitConnection.resolve_repo_commits,
        **LogCommitConnection.get_repo_commits_input_fields()
    )
    tree = relay.ConnectionField(
        Tree,
        resolver=Tree.resolve_repo_tree,
        **Tree.get_repo_tree_input_fields()
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
        cache_in_context(info.context, 'repo', repo)
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
