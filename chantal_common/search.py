#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# This file is part of Chantal, the samples database.
#
# Copyright (C) 2010 Forschungszentrum Jülich, Germany,
#                    Marvin Goblet <m.goblet@fz-juelich.de>,
#                    Torsten Bronger <t.bronger@fz-juelich.de>
#
# You must not use, install, pass on, offer, sell, analyse, modify, or
# distribute this software without explicit permission of the copyright holder.
# If you have received a copy of this software without the explicit permission
# of the copyright holder, you must destroy it immediately and completely.

from __future__ import absolute_import
from django import forms
from django.utils.safestring import mark_safe
from django.utils.encoding import force_unicode
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from django.db.models import get_models, get_app
from django.db import models


def convert_fields_to_search_fields(cls, excluded_fieldnames=[]):
    search_fields = []
    for field in cls._meta.fields:
        if field.name not in excluded_fieldnames + ["id", "actual_object_id"]:
            if field.choices:
                search_fields.append(ChoiceSearchField(cls, field))
            elif type(field) in [models.CharField, models.TextField]:
                search_fields.append(TextSearchField(cls, field))
            elif type(field) in [models.AutoField, models.BigIntegerField, models.IntegerField, models.FloatField,
                                 models.DecimalField, models.PositiveIntegerField, models.PositiveSmallIntegerField,
                                 models.SmallIntegerField]:
                search_fields.append(IntervalSearchField(cls, field))
            elif type(field) == models.DateTimeField:
                search_fields.append(DateTimeSearchField(cls, field))
            elif type(field) == models.BooleanField:
                search_fields.append(BooleanSearchField(cls, field))
    return search_fields


class SearchField(object):

    def __init__(self, cls, field_or_field_name, additional_query_path=""):
        self.field = cls._meta.get_field(field_or_field_name) if isinstance(field_or_field_name, basestring) \
            else field_or_field_name
        self.query_path = self.field.name
        if additional_query_path:
            self.query_path += "__" + additional_query_path

    def parse_data(self, data, prefix):
        raise NotImplementedError

    def get_values(self):
        result = self.form.cleaned_data[self.field.name]
        return {self.query_path: result} if result is not None else {}

    def is_valid(self):
        return self.form.is_valid()


class RangeSearchField(SearchField):
    
    def get_values(self):
        result = {}
        min_value = self.form.cleaned_data[self.field.name + "_min"]
        max_value = self.form.cleaned_data[self.field.name + "_max"]
        if min_value is not None and max_value is not None:
            result[self.query_path + "__range"] = (min_value, max_value)
        elif min_value is not None:
            result[self.query_path + "__gte"] = min_value
        elif max_value is not None:
            result[self.query_path + "__lte"] = max_value
        return result


class TextSearchField(SearchField):

    def parse_data(self, data, prefix):
        self.form = forms.Form(data, prefix=prefix)
        self.form.fields[self.field.name] = forms.CharField(label=unicode(self.field.verbose_name), required=False,
                                                            help_text=self.field.help_text)

    def get_values(self):
        result = self.form.cleaned_data[self.field.name]
        return {self.query_path + "__icontains": result} if result else {}


class IntegerSearchField(SearchField):
    
    def parse_data(self, data, prefix):
        self.form = forms.Form(data, prefix=prefix)
        self.form.fields[self.field.name] = forms.IntegerField(label=unicode(self.field.verbose_name), required=False,
                                                               help_text=self.field.help_text)


class IntervalSearchField(RangeSearchField):
    
    def parse_data(self, data, prefix):
        self.form = forms.Form(data, prefix=prefix)
        self.form.fields[self.field.name + "_min"] = forms.FloatField(label=unicode(self.field.verbose_name), required=False,
                                                                      help_text=self.field.help_text)
        self.form.fields[self.field.name + "_max"] = forms.FloatField(label=unicode(self.field.verbose_name), required=False,
                                                                      help_text=self.field.help_text)


class ChoiceSearchField(SearchField):

    def parse_data(self, data, prefix):
        self.form = forms.Form(data, prefix=prefix)
        field = forms.ChoiceField(label=unicode(self.field.verbose_name), required=False, help_text=self.field.help_text)
        field.choices = [("", u"---------")] + list(self.field.choices)
        self.form.fields[self.field.name] = field

    def get_values(self):
        result = self.form.cleaned_data[self.field.name]
        return {self.query_path: result} if result else {}


class DateTimeSearchField(RangeSearchField):

    def parse_data(self, data, prefix):
        self.form = forms.Form(data, prefix=prefix)
        self.form.fields[self.field.name + "_min"] = forms.DateTimeField(label=unicode(self.field.verbose_name),
                                                                         required=False, help_text=self.field.help_text)
        self.form.fields[self.field.name + "_max"] = forms.DateTimeField(label=unicode(self.field.verbose_name),
                                                                         required=False, help_text=self.field.help_text)


class BooleanSearchField(SearchField):

    class SimpleRadioSelectRenderer(forms.widgets.RadioFieldRenderer):
        def render(self):
            return mark_safe(u"""<ul class="radio-select">\n{0}\n</ul>""".format(u"\n".join(
                        u"<li>{0}</li>".format(force_unicode(w)) for w in self)))

    def parse_data(self, data, prefix):
        self.form = forms.Form(data, prefix=prefix)
        self.form.fields[self.field.name] = forms.ChoiceField(
            label=unicode(self.field.verbose_name), required=False,
            choices=(("", _(u"doesn't matter")), ("yes", _(u"yes")), ("no", _(u"no"))),
            widget=forms.RadioSelect(renderer=self.SimpleRadioSelectRenderer), help_text=self.field.help_text)

    def get_values(self):
        result = self.form.cleaned_data[self.field.name]
        return {self.query_path: result == "yes"} if result else {}


class SearchModelForm(forms.Form):
    _model = forms.ChoiceField(label=_(u"containing"), required=False)
    _old_model = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, models, data=None, **kwargs):
        super(SearchModelForm, self).__init__(data, **kwargs)
        self.fields["_model"].choices = [("", u"---------")] + \
            [(model.__name__, model._meta.verbose_name) for model in models]


all_models = None
def get_model(model_name):
    global all_models
    if all_models is None:
        all_models = {}
        for app in [get_app(app.rpartition(".")[2]) for app in settings.INSTALLED_APPS]:
            all_models.update((model.__name__, model) for model in get_models(app))
    return all_models[model_name]


class SearchTreeNode(object):

    def __init__(self, model_class, related_models, search_fields):
        self.related_models = related_models
        self.model_class = model_class
        self.children = []
        self.search_fields = search_fields

    def parse_data(self, data, prefix):
        for search_field in self.search_fields:
            search_field.parse_data(data, prefix)
        data = data or {}
        depth = prefix.count("-") + (2 if prefix else 1)
        keys = [key for key in data if key.count("-") == depth]
        i = 1
        while True:
            new_prefix = prefix + ("-" if prefix else "") + str(i)
            if not data.get(new_prefix + "-_model"):
                break
            search_model_form = SearchModelForm(self.related_models.keys(), data, prefix=new_prefix)
            if not search_model_form.is_valid():
                break
            model_name = data[new_prefix + "-_model"]
            model_field = get_model(model_name).get_search_tree_node()
            parse_model = search_model_form.cleaned_data["_model"] == search_model_form.cleaned_data["_old_model"]
            model_field.parse_data(data if parse_model else None, new_prefix)
            search_model_form = SearchModelForm(self.related_models.keys(),
                                                initial={"_old_model": search_model_form.cleaned_data["_model"],
                                                         "_model": search_model_form.cleaned_data["_model"]},
                                                prefix=new_prefix)
            self.children.append((search_model_form, model_field))
            i += 1
        if self.related_models:
            self.children.append((SearchModelForm(self.related_models.keys(), prefix=new_prefix), None))

    def get_search_results(self, top_level=True):
        kwargs = {}
        for search_field in self.search_fields:
            if search_field.get_values():
                kwargs.update(search_field.get_values())
        result = self.model_class.objects.filter(**kwargs)
        kwargs = {}
        for child in self.children:
            if child[1]:
                name = self.related_models[child[1].model_class] + "__pk__in"
                kwargs[name] = child[1].get_search_results(False)
        result = result.filter(**kwargs)
        if top_level:
            return self.model_class.objects.in_bulk(list(result.values_list("pk", flat=True))).values()
        else:
            return result.values("pk")

    def is_valid(self):
        is_all_valid = True
        for search_field in self.search_fields:
            is_all_valid = is_all_valid and search_field.is_valid()
        if self.children:
            for child in self.children:
                if child[1]:
                    is_all_valid = is_all_valid and child[1].is_valid()
        return is_all_valid
