from django.contrib import admin

from .models import RepoModel


admin.site.site_header = 'Kroftig Administration'
admin.site.site_title = 'Kroftig Admin'

admin.site.register(RepoModel)
