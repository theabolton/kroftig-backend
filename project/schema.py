# Kroftig backend project/schema.py
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

import graphene

import kroftig.schema

from.settings import DEBUG


class Query(kroftig.schema.Query, graphene.ObjectType):
    pass


class Mutation(kroftig.schema.Mutation, graphene.ObjectType):
    pass


schema = graphene.Schema(query=Query, mutation=Mutation)


# GraphQL query/mutation fields (and their parent type names) which may be accessed without being
# logged in.
VALID_UNAUTHENTICATED_FIELDS = (
    # (info.field_name, info.parent_type.name)
    ('logIn', 'Mutation'),
    ('logOut', 'Mutation'),
    ('success', 'LogOutPayload'),
)


class AuthMiddleware(object):
    def resolve(self, next, root, info, **args):
        if info.context.user.is_authenticated:
            return next(root, info, **args)
        if (info.field_name, info.parent_type.name) in VALID_UNAUTHENTICATED_FIELDS:
            return next(root, info, **args)
        if DEBUG and 'HTTP_X_KROFTIG_DEBUG_ALLOW' in info.context.META:
            return next(root, info, **args)
        raise Exception('access denied, please log in')
