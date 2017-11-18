# Kroftig backend kroftig/tests.py
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
import subprocess
import tempfile
import traceback

from django.test import SimpleTestCase
import graphene
from graphql.error import GraphQLError

from project.schema import Query


# ========== utility functions ==========

def format_graphql_errors(errors):
    """Return a string with the usual exception traceback, plus some extra fields that GraphQL
    provides.
    """
    if not errors:
        return None
    text = []
    for i, e in enumerate(errors):
        text.append('GraphQL schema execution error [{}]:\n'.format(i))
        if isinstance(e, GraphQLError):
            for attr in ('args', 'locations', 'nodes', 'positions', 'source'):
                if hasattr(e, attr):
                    if attr == 'source':
                        text.append('source: {}:{}\n'
                                    .format(e.source.name, e.source.body))
                    else:
                        text.append('{}: {}\n'.format(attr, repr(getattr(e, attr))))
        if isinstance(e, Exception):
            text.append(''.join(traceback.format_exception(type(e), e, e.stack)))
        else:
            text.append(repr(e) + '\n')
    return ''.join(text)


def set_up_test_repo():
    """Creates a repository for testing. Creates a temporary directory under, then untars the
    tar archive ./kroftig/fixtures/test_repo.tar.xz into that. Returns a tuple
    (tempfile temporary directory object, path to repo).
    """
    tempdir = tempfile.TemporaryDirectory(prefix='kroftig-tmp-')
    subprocess.run([
        'tar',
        '-C', tempdir.name,
        '-x', '-p',
        '-f', './kroftig/fixtures/test_repo.tar.xz',
    ])
    return (tempdir, os.path.join(tempdir.name, 'test_repo'))


def tear_down_test_repo(tempdir):
    tempdir.cleanup()


# ========== GraphQL schema general tests ==========

class RootTests(SimpleTestCase):
    def test_root_query(self):
        """Make sure the root query is 'Query'.

        This test is pretty redundant, given that every other query in this file will fail if this
        is not the case, but it's a nice simple example of testing query execution.
        """
        query = '''
          query RootQueryQuery {
            __schema {
              queryType {
                name  # returns the type of the root query
              }
            }
          }
        '''
        expected = {
            '__schema': {
                'queryType': {
                    'name': 'Query'
                }
            }
        }
        schema = graphene.Schema(query=Query)
        result = schema.execute(query)
        self.assertIsNone(result.errors, msg=format_graphql_errors(result.errors))
        self.assertEqual(result.data, expected, msg='\n'+repr(expected)+'\n'+repr(result.data))


# ========== Relay Node tests ==========

class RelayNodeTests(SimpleTestCase):
    """Test that model nodes can be retreived via the Relay Node interface."""

    # These tests are read-only, so we can set up the test repo once for all of them.
    @classmethod
    def setUpClass(cls):
        (cls.tempdir, cls.repo) = set_up_test_repo()

    @classmethod
    def tearDownClass(cls):
        tear_down_test_repo(cls.tempdir)

    def test_node_for_repo(self):
        query = '''
          query {
            repo {
              id
            }
          }
        '''
        schema = graphene.Schema(query=Query)
        result = schema.execute(query)
        self.assertIsNone(result.errors, msg=format_graphql_errors(result.errors))
        repo_gid = result.data['repo']['id']
        query = '''
          query {
            node(id: "%s") {
              id
            }
          }
        ''' % repo_gid
        expected = {
          'node': {
            'id': repo_gid,
          }
        }
        result = schema.execute(query)
        self.assertIsNone(result.errors, msg=format_graphql_errors(result.errors))
        self.assertEqual(result.data, expected, msg='\n'+repr(expected)+'\n'+repr(result.data))

    def test_node_for_log_commit(self):
        query = '''
          query TestNodeForLogCommit {
            repo {
              commits(first: 1) {
                edges {
                  node {
                    id
                    message
                  }
                }
              }
            }
          }
        '''
        schema = graphene.Schema(query=Query)
        result = schema.execute(query)
        self.assertIsNone(result.errors, msg=format_graphql_errors(result.errors))
        commit = result.data['repo']['commits']['edges'][0]['node']
        commit_gid = commit['id']
        commit_message = commit['message']
        query = '''
          query {
            node(id: "%s") {
              id
              ...on LogCommit {
                message
              }
            }
          }
        ''' % commit_gid
        expected = {
          'node': {
            'id': commit_gid,
            'message': commit_message,
          }
        }
        schema = graphene.Schema(query=Query)
        result = schema.execute(query)
        self.assertIsNone(result.errors, msg=format_graphql_errors(result.errors))
        self.assertEqual(result.data, expected, msg='\n'+repr(expected)+'\n'+repr(result.data))
