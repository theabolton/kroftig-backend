import graphene
from graphene.relay import Node
#from graphene_django.types import DjangoObjectType

#from ingredients.models import Category, Ingredient


#class IngredientType(DjangoObjectType):
#    class Meta:
#        model = Ingredient

class Query(object):
    log = graphene.String()
    node = Node.Field()

    def resolve_log(_, info, **args):
        return('Log!')

    #all_ingredients = graphene.List(IngredientType)

    #def resolve_all_categories(self, info, **kwargs):
    #    return Category.objects.all()

    #def resolve_all_ingredients(self, info, **kwargs):
    #    # We can easily optimize query count in the resolve method
    #    return Ingredient.objects.select_related('category').all()
