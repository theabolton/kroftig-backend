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
import os

from django.contrib.auth import authenticate, get_user_model, login, logout
import django.contrib.humanize.templatetags.humanize as humanize
import graphene
from graphene import ObjectType, relay
from graphene.relay import Node
from graphene_django import DjangoObjectType
import pygit2 as git

from .git_utils import get_latest_changing_commits_for_tree
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


class User(DjangoObjectType):
    class Meta:
        model = get_user_model()
        only_fields = ['id', 'username', 'first_name', 'last_name', 'email', 'is_staff',
                       'is_active']


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


class TreeEntry(ObjectType):
    class Meta:
        interfaces = (Node, )

    oid = graphene.String()
    name = graphene.String()
    filemode = graphene.Int()
    type_ = graphene.String(name='type')
    size = graphene.Int()
    latest_commit = graphene.Field('kroftig.schema.Commit')

    def resolve_size(entry: 'TreeEntry', info, **args):
        repo = get_from_context_cache(info.context, 'repo')
        obj = repo.git_repo.get(entry.oid)
        if obj.type == git.GIT_OBJ_BLOB:
            return obj.size
        return None

    def resolve_latest_commit(entry: 'TreeEntry', info, **args):
        """Node IDs for TreeEntrys are of the form (before base64 encoding):
        'TreeEntry:<repo_name>^<commit-sha-in-hex>^<file-path>'.
        """
        (_, commit_id, path) = entry.id.split('^', maxsplit=2)
        repo = get_from_context_cache(info.context, 'repo')
        # get_latest_changing_commits_for_tree() is expensive and returns results for the entire
        # tree, so cache its results.
        try:
            latests = get_from_context_cache(info.context, 'latests')
        except KeyError:
            git_repo = repo.git_repo
            if '/' in path:
                filter_path = path[:path.rfind('/')]
            else:
                filter_path = ''
            latests = get_latest_changing_commits_for_tree(git_repo, git_repo.get(commit_id),
                                                           filter_path)
            cache_in_context(info.context, 'latests', latests)
        try:
            commit = latests[path]['latest']
            return Commit.build_instance(repo.name + '^' + commit.hex, commit)
        except:
            return None

    @staticmethod
    def build_instance(id, entry):
        if entry.filemode == git.GIT_FILEMODE_LINK:
            type_ = 'link'
        else:
            type_ = entry.type
        return TreeEntry(id=id, oid=entry.hex, name=entry.name, filemode=entry.filemode,
                         type_=type_)

    @classmethod
    def get_node(cls, info, id):
        (repo_name, commit_id, path) = id.split('^', maxsplit=2)
        repo = get_repo_from_name(repo_name)
        if not repo:
            return None
        cache_in_context(info.context, 'repo', repo)
        git_repo = repo.git_repo
        commit = git_repo.get(commit_id)
        if not commit:
            return None
        try:
            entry = commit.tree[path]
        except:
            return None
        return TreeEntry.build_instance(id, entry)


class Tree(relay.Connection):
    class Meta:
        node = TreeEntry

    @staticmethod
    def build_instance(repo_name, commit, tree, path):
        path = path or ''
        entries = []
        for entry in tree:
            id = repo_name + '^' + commit.hex + '^' + os.path.join(path, entry.name)
            entries.append(TreeEntry.build_instance(id, entry))
        entries.sort(key=lambda e: (e.type_ == 'tree' and '0' or '1') + e.name)
        return entries

    def resolve_commit_tree(commit: 'Commit', info, **args):
        """Resolver for Commit field 'tree'."""
        repo = get_from_context_cache(info.context, 'repo')
        git_repo = repo.git_repo
        commit = git_repo.get(commit.oid)
        return Tree.build_instance(repo.name, commit, commit.tree, '')

    @staticmethod
    def get_repo_tree_input_fields():
        """Input fields for Repo field 'tree'."""
        return {
            'rev': graphene.Argument(graphene.String, required=True),
            'path': graphene.Argument(graphene.String),
        }

    def resolve_repo_tree(repo: RepoModel, info, **args):
        """Resolver for Repo field 'tree'."""
        git_repo = repo.git_repo
        rev = args.get('rev')
        try:
            commit = git_repo.revparse_single(rev)
            tree = commit.tree
        except (KeyError, ValueError):
            raise Exception("commit reference '{}' not found".format(rev))
        path = args.get('path')
        if path:
            try:
                entry = commit.tree[path]
                assert entry.type == 'tree'
            except:
                raise Exception("commit {}: bad tree path '{}'".format(commit.hex, path))
            tree = git_repo.get(entry.oid)
        return Tree.build_instance(repo.name, commit, tree, path)


class Commit(ObjectType):
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
    tree = relay.ConnectionField(Tree, resolver=Tree.resolve_commit_tree,
                                 description="Relatively expensive, only fetch if needed")

    @staticmethod
    def build_instance(id, commit):
        if not commit:
            return None
        return Commit(id=id, oid=commit.hex, message=commit.message,
                      author=commit.author.name, author_time=humantime(commit.author.time),
                      author_email=commit.author.email,
                      committer=commit.committer.name,
                      committer_time=humantime(commit.committer.time),
                      committer_email=commit.committer.email,
                      parent_ids=commit.parent_ids)

    @classmethod
    def get_node(cls, info, id):
        """Node IDs for Commits are of the form (before base64 encoding):
        'Commit:<repo_name>^<commit-sha-in-hex>'.
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
        return Commit.build_instance(repo.name + '^' + commit.hex, commit)


class CommitConnection(relay.Connection):
    class Meta:
        node = Commit

    rev = graphene.String()

    def resolve_rev(connection: 'CommitConnection', info, **args):
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
            commits.append(Commit.build_instance(repo.name + '^' + commit.hex, commit))
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
        Commit,
        resolver=Commit.resolve_repo_commit,
        **Commit.get_repo_commit_input_fields()
    )
    commits = relay.ConnectionField(
        CommitConnection,
        resolver=CommitConnection.resolve_repo_commits,
        **CommitConnection.get_repo_commits_input_fields()
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
    user = graphene.Field(User)
    users = graphene.List(User)

    def resolve_repos(_, info):
        return RepoModel.objects.all().order_by('name')

    def resolve_user(_, info):
        if not info.context.user or not isinstance(info.context.user, get_user_model()):
           return None
        return info.context.user

    def resolve_users(_, info):
        return get_user_model().objects.all().order_by('username')


class LogIn(relay.ClientIDMutation):
    user = graphene.Field(User)

    class Input:
        username = graphene.String(required=True)
        password = graphene.String(required=True)

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        username = input.get('username')
        password = input.get('password')
        user = authenticate(username=username, password=password)
        if not user or not user.is_active:
            raise Exception('invalid login')
        login(info.context, user)
        return cls(user=user)


class LogOut(relay.ClientIDMutation):
    success = graphene.Boolean() # must return something

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        logout(info.context)
        return cls(success=True)


class Mutation(object):
    log_in = LogIn.Field()
    log_out = LogOut.Field()
