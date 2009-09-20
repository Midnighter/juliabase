#!/usr/bin/env python
# -*- coding: utf-8 -*-

u"""View and routines for the bulk view.  In the bulk view, the results of a
search are displayed in pages.  Additionally, it is used to visualise
references lists.
"""

from __future__ import absolute_import

from . import form_utils
from django.template import RequestContext
from django.shortcuts import render_to_response
from django.views.decorators.http import last_modified, require_http_methods
from django.utils.http import urlencode
from django.utils.translation import ugettext as _, ungettext, ugettext_lazy
from django.contrib.auth.decorators import login_required
from django import forms
from django.core.cache import cache
from django.conf import settings
from .. import refdb
from . import utils, form_utils


class SearchForm(forms.Form):
    u"""Form class for the search filters.  Currently, it only accepts a RefDB
    query string.
    """

    _ = ugettext_lazy
    query_string = forms.CharField(label=_("Query string"), required=False)


class SelectionBoxForm(forms.Form):
    u"""Form class for the tick box for each reference.  This micro-form is
    generated for each reference in the bulk view.  The actions of the central
    dispatch are performed only on selected references.
    """
    _ = ugettext_lazy
    selected = forms.BooleanField(label=_("selected"), required=False)


output_format_choices = (
    ("ris", u"RIS"),
    ("html", u"HTML"),
    ("xhtml", u"XHTML"),
    ("db31", u"DocBook 3.1"),
    ("db31x", u"DocBook XML 3.1"),
    ("db50", u"DocBook 5.0"),
    ("db50x", u"DocBook XML 3.1"),
    ("teix", u"TEI XML"),
    ("tei5x", u"TEI 5 XML"),
    ("mods", u"MODS"),
    ("bibtex", u"BibTeX"),
    ("rtf", u"RTF")
    )

class ExportForm(forms.Form):
    u"""Form class for exporting references to a particular output format.
    """
    _ = ugettext_lazy
    format = forms.ChoiceField(label=_("Export as"), choices=(("", 9*u"-"),) + output_format_choices, required=False)


class RemoveFromListForm(forms.Form):
    u"""Form class for removing references from a references list.
    """
    _ = ugettext_lazy
    remove = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        verbose_listname = kwargs.pop("verbose_listname", None)
        super(RemoveFromListForm, self).__init__(*args, **kwargs)
        if verbose_listname:
            self.fields["remove"].label = _(u"Remove from list “%s”") % verbose_listname


class AddToShelfForm(forms.Form):
    u"""Form class for adding references to a shelf.
    """
    _ = ugettext_lazy
    new_shelf = forms.ChoiceField(label=_("Add to shelf"), required=False)

    def __init__(self, *args, **kwargs):
        super(AddToShelfForm, self).__init__(*args, **kwargs)
        self.fields["new_shelf"].choices = \
            [("", 9*u"-")] + [(shelf.pk, unicode(shelf)) for shelf in models.Shelf.objects.all()]


class AddToListForm(forms.Form):
    u"""Form class for adding references to a references list.  The user has
    the option to add to an existing list (only `existing_list` is filled) or
    to a new list (only `new_list` is filled).  He must not give both fields.
    """
    _ = ugettext_lazy
    existing_list = forms.ChoiceField(label=_("List"), required=False)
    new_list = forms.CharField(label=_("New list"), max_length=255, required=False)

    def __init__(self, user, *args, **kwargs):
        u"""Class constructor.

        :Parameters:
          - `user`: current user

        :type user: ``django.contrib.auth.models.User``
        """
        super(AddToListForm, self).__init__(*args, **kwargs)
        lists = refdb.get_lists(user)[0]
        self.short_listnames = set(list_[0] for list_ in lists)
        self.fields["existing_list"].choices = [("", 9*"-")] + lists
        self.optional = True

    def clean(self):
        u"""Class clean method which assures that at most one of the fields is
        given.  Additionally, it checks that the name for a new list doesn't
        already exist in the database.
        """
        _ = ugettext
        cleaned_data = self.cleaned_data
        if cleaned_data["existing_list"] and cleaned_data["new_list"]:
            append_error(self, _(u"You must not give both an existing and a new list."), "new_list")
            del cleaned_data["new_list"], cleaned_data["existing_list"]
        elif not self.optional and not cleaned_data["existing_list"] and not cleaned_data["new_list"]:
            append_error(self, _(u"You must give either an existing or a new list."), "new_list")
            del cleaned_data["new_list"], cleaned_data["existing_list"]
        elif cleaned_data["new_list"] and cleaned_data["new_list"] in self.short_listnames:
            append_error(self, _(u"This listname is already given."), "new_list")
            del cleaned_data["new_list"]
        return cleaned_data


@login_required
def search(request):
    u"""Searchs for references and presents the search results.

    :Parameters:
      - `request`: the current HTTP Request object

    :type request: ``HttpRequest``

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    search_form = SearchForm(request.GET)
    return render_to_response("search.html", {"title": _(u"Search"), "search": search_form},
                              context_instance=RequestContext(request))


def form_fields_to_query(form_fields):
    u"""Takes the GET parameters of the bulk view and distills a RefDB query
    string from them.

    :Parameters:
      - `form_fields`: dictionary which maps all search parameters to their
        values (and maybe more, which is ignored)

    :type form_fields: ``django.http.QueryDict``

    :Return:
      the RefDB query string representing the search

    :rtype: unicode
    """
    query_string = form_fields.get("query_string", "")
    return query_string


def add_references_to_list(ids, add_to_list_form, user):
    u"""Add references to a references list.

    :Parameters:
      - `ids`: RefDB IDs of the references to be added
      - `add_to_list_form`: bound and valid form containing the list to be
        added to
      - `user`: current user

    :type ids: list of str
    :type add_to_list_form: ``django.forms.Form``
    :type user: ``django.contrib.auth.models.User``
    """
    # add_to_list_form must be bound and valid
    if add_to_list_form.cleaned_data["existing_list"]:
        listname = add_to_list_form.cleaned_data["existing_list"]
    else:
        verbose_name = add_to_list_form.cleaned_data["new_list"]
        listname = defaultfilters.slugify(verbose_name)
    connection = refdb.get_connection(user)
    connection.pick_references(ids, listname)
    if add_to_list_form.cleaned_data["new_list"]:
        extended_note = connection.get_extended_notes(":NCK:=%s-%s" % (refdb.get_username(user.id), listname))[0]
        extended_note.set_text_content(verbose_name)
        connection.update_extended_notes(extended_note)


def is_all_valid(export_form, add_to_shelf_form, add_to_list_form, remove_from_list_form, selection_box_forms):
    all_valid = export_form.is_valid()
    all_valid = add_to_shelf_form.is_valid() and all_valid
    all_valid = add_to_list_form.is_valid() and all_valid
    all_valid = remove_from_list_form.is_valid() and all_valid
    all_valid = all([form.is_valid() for form in selection_box_forms]) and all_valid
    return all_valid


def is_referentially_valid(export_form, add_to_shelf_form, add_to_list_form, remove_from_list_form,
                           selection_box_forms, global_dummy_form, references_list):
    u"""Test whether all forms are consistent with each other.  In particular,
    the user must use exactly one of the given forms.  He must not try to
    export references and add them to a shelf at the same time.

    :Parameters:
      - `export_form`: bound form for exporting references
      - `add_to_shelf_form`: bound form for adding references to a shelf
      - `add_to_list_form`: bound form for adding references to a references
        list
      - `remove_from_list_form`: bound form for removing references form a
        references list; may be ``None`` if the search is not limited to a
        particular references list
      - `selection_box_forms`: bound forms with the selected samples
      - `global_dummy_form`: bound form which contains global error messages
        which occur here
      - `references_list`: the references list the bulk view is limited to

    :type export_form: ``form_utils.ExportForm``
    :type add_to_shelf_form: ``form_utils.AddToShelfForm``
    :type add_to_list_form: ``form_utils.AddToListForm``
    :type remove_from_list_form: ``form_utils.RemoveFromListForm`` or
      ``NoneType``
    :type selection_box_forms: list of ``form_utils.SelectionBoxForm``
    :type global_dummy_form: ``django.forms.Form``
    :type references_list: unicode

    :Return:
      whether all forms are consistent and obey to the constraints

    :rtype: bool
    """
    referentially_valid = True
    action = None
    actions = []
    if export_form.is_valid() and export_form.cleaned_data["format"]:
        actions.append("export")
    if add_to_shelf_form.is_valid() and add_to_shelf_form.cleaned_data["new_shelf"]:
        actions.append("shelf")
    if add_to_list_form.is_valid() and (
        add_to_list_form.cleaned_data["existing_list"] or add_to_list_form.cleaned_data["new_list"]):
        actions.append("list")
    if references_list and remove_from_list_form.is_valid() and remove_from_list_form.cleaned_data["remove"]:
        actions.append("remove")
    if not actions:
        referentially_valid = False
        if export_form.is_valid() and add_to_shelf_form.is_valid() and add_to_list_form.is_valid() and \
                remove_from_list_form.is_valid():
            form_utils.append_error(global_dummy_form, _(u"You must select an action."))
    elif len(actions) > 1:
        form_utils.append_error(global_dummy_form, _(u"You can't do more that one thing at the same time."))
        referentially_valid = False
    else:
        action = actions[0]
    if not any(selection_box_form.is_valid() and selection_box_form.cleaned_data["selected"]
               for selection_box_form in selection_box_forms):
        form_utils.append_error(global_dummy_form, _(u"You must select at least one sample."))
        referentially_valid = False
    return referentially_valid, action


class CommonBulkViewData(object):
    u"""Container class for data used in `get_last_modification_date` as well
    as in the `bulk` view itself.  The rationale for this class is the
    ``get_last_modification_date`` has to calculate some data in a somewhat
    expensive manner – for example, it has to make a RefDB server connection.
    This data is also used in the ``bulk`` view, and it would be wasteful to
    calculate it there again.

    Thus, an instance of this class holds the data and is written as an
    attribute to the ``request`` object.
    """

    def __init__(self, query_string, offset, limit, refdb_connection, ids):
        u"""Class constructor.

        :Parameters:
          - `query_string`: RefDB query string of this search
          - `offset`: the starting index of the bulk list amongst the search
            hits
          - `limit`: the number of displayed hits
          - `refdb_connection`: connection object to the RefDB server
          - `ids`: IDs of the found references (within ``offset`` and
            ``limit``)

        :type query_string: unicode
        :type offset: int
        :type limit: int
        :type refdb_connection: ``pyrefdb.Connection``
        :type ids: list of str
        """
        self.query_string, self.offset, self.limit, self.refdb_connection, self.ids = \
            query_string, offset, limit, refdb_connection, ids

    def get_all_values(self):
        u"""Returns all data stored in the instance.

        :Return:
          query string, search hits offset, maximal number of search hits,
          RefDB connection, IDs of found references

        :rtype: unicode, int, int, ``pyrefdb.Connection``, list of str
        """
        return self.query_string, self.offset, self.limit, self.refdb_connection, self.ids


def embed_common_data(request):
    query_string = form_fields_to_query(request.GET)
    offset = request.GET.get("offset")
    limit = request.GET.get("limit")
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    refdb_connection = refdb.get_connection(request.user)
    ids = refdb_connection.get_references(query_string, output_format="ids", offset=offset, limit=limit)
    request.common_data = CommonBulkViewData(query_string, offset, limit, refdb_connection, ids)


def fetch_references(request):

    def build_page_link(new_offset):
        u"""Generate the URL to another page of the current search view.  If
        there are too many search hits, the hits are split on multiple pages
        with their own offsets.  This routine builds the relative URLs to
        them.  Since ``bulk`` is a pure GET view, I just need to make sure that
        all GET parameters survive in the link.

        :Parameters:
          - `new_offset`: search hits offset for the destination page

        :type new_offset: int

        :Return:
          the relative URL to a page with the same GET parameters
        """
        new_query_dict = request.GET.copy()
        new_query_dict["offset"] = new_offset
        # I also set ``limit`` because it may have been adjusted in
        # `get_last_modification_date`
        new_query_dict["limit"] = limit
        return "?" + urlencode(new_query_dict) if 0 <= new_offset < number_of_references and new_offset != offset else None

    query_string, offset, limit, refdb_connection, ids = request.common_data.get_all_values()
    number_of_references = refdb_connection.count_references(query_string)
    prev_link = build_page_link(offset - limit)
    next_link = build_page_link(offset + limit)
    pages = []
    for i in range(number_of_references // limit + 1):
        link = build_page_link(i * limit)
        pages.append(link)
    all_references = cache.get_many(settings.REFDB_CACHE_PREFIX + id_ for id_ in ids)
    length_cache_prefix = len(settings.REFDB_CACHE_PREFIX)
    all_references = dict((cache_id[length_cache_prefix:], reference) for cache_id, reference in all_references.iteritems())
    missing_ids = set(ids) - set(all_references)
    if missing_ids:
        missing_references = refdb_connection.get_references(u" OR ".join(":ID:=" + id_ for id_ in missing_ids))
        missing_references = dict((reference.id, reference) for reference in missing_references)
        all_references.update(missing_references)
    references = [all_references[id_] for id_ in ids]
    for reference in references:
        reference.fetch(["shelves", "global_pdf_available", "users_with_offprint", "relevance", "comments",
                         "pdf_is_private", "creator", "institute_publication"], refdb_connection, request.user.pk)
        cache.set(settings.REFDB_CACHE_PREFIX + reference.id, reference)
    return references, prev_link, next_link, pages


def get_last_modification_date(request):
    u"""Returns the last modification of the references found for the bulk
    view.  Note that this only includes the actually *displayed* references on
    the current page, not all references from all pages

    The routine is only used in the ``last_modified`` decorator in `bulk`.

    :Parameters:
      - `request`: current HTTP request object

    :type request: ``HttpRequest``

    :Return:
      timestamp of last modification of the displayed references

    :rtype: ``datetime.datetime``
    """
    if request.method == "GET":
        embed_common_data(request)
        last_modified = utils.last_modified(request.user, request.common_data.ids)
    else:
        last_modified = None
    return last_modified


@login_required
@last_modified(get_last_modification_date)
def bulk(request):
    u"""The bulk view for references.  It gets the search parameters in the
    GET, and displays all references which matches the search parameters.  If
    they are too many, the list is split up into pages where you can navigate
    through.

    I do agressive caching here.  First, I use the ``@last_modified`` decorator
    for making use of the browser cache.  Secondly, I cache all references
    objects requested for later use, including their “extended attributes”.  If
    a second request needs more extended atttibutes, only the missing ones are
    fetched.

    :Parameters:
      - `request`: the current HTTP Request object

    :type request: ``HttpRequest``

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    references_list = request.GET.get("list")
    if request.method == "POST":
        export_form = form_utils.ExportForm(request.POST)
        add_to_shelf_form = form_utils.AddToShelfForm(request.POST)
        add_to_list_form = form_utils.AddToListForm(request.user, request.POST)
        remove_from_list_form = form_utils.RemoveFromListForm(request.POST)
        global_dummy_form = forms.Form(request.POST)
        ids = set()
        for key, value in request.POST.iteritems():
            id_, dash, name = key.partition("-")
            if name == "selected" and value == "on":
                ids.add(id_)
        selection_box_forms = [form_utils.SelectionBoxForm(request.POST, prefix=id_) for id_ in ids]
        all_valid = \
            is_all_valid(export_form, add_to_shelf_form, add_to_list_form, remove_from_list_form, selection_box_forms)
        referentially_valid, action = is_referentially_valid(
            export_form, add_to_shelf_form, add_to_list_form, remove_from_list_form, selection_box_forms, global_dummy_form,
            references_list)
        valid_post_data = all_valid and referentially_valid
        if valid_post_data:
            if action == "export":
                query_dict = {"format": export_form.cleaned_data["format"]}
                query_dict.update((id_ + "-selected", "on") for id_ in ids)
                query_string = urlencode(query_dict)
                return utils.HttpResponseSeeOther(django.core.urlresolvers.reverse(export) + "?" + query_string)
            elif action == "shelf":
                # FixMe: This must be changed from using citation keys to using
                # IDs.  However, first
                # https://sourceforge.net/tracker/?func=detail&aid=2857792&group_id=26091&atid=385991
                # needs to be fixed.
                citation_keys = [reference.citation_key for reference in refdb.get_connection(request.user).
                                 get_references(" OR ".join(":ID:=" + id_ for id_ in ids))]
                refdb.get_connection(request.user).add_note_links(
                    ":NCK:=django-refdb-shelf-" + add_to_shelf_form.cleaned_data["new_shelf"],
                    u" ".join(":CK:=" + citation_key for citation_key in citation_keys))
            elif action == "list":
                add_references_to_list(ids, add_to_list_form, request.user)
            elif action == "remove":
                refdb.get_connection(request.user).dump_references(ids, remove_from_list_form.cleaned_data["listname"])
        embed_common_data(request)
        if not valid_post_data:
            references, prev_link, next_link, pages = fetch_references(request)
            for reference in references:
                reference.selection_box = form_utils.SelectionBoxForm(request.POST, prefix=reference.id)
    else:
        valid_post_data = False
    if request.method == "GET" or valid_post_data:
        references, prev_link, next_link, pages = fetch_references(request)
        for reference in references:
            reference.selection_box = form_utils.SelectionBoxForm(prefix=reference.id)
        export_form = form_utils.ExportForm()
        add_to_shelf_form = form_utils.AddToShelfForm()
        add_to_list_form = form_utils.AddToListForm(request.user)
        global_dummy_form = forms.Form()
        if references_list:
            verbose_listname = refdb.get_verbose_listname(references_list, request.user)
            remove_from_list_form = form_utils.RemoveFromListForm(
                initial={"listname": references_list}, verbose_listname=verbose_listname, prefix="remove")
        else:
            remove_from_list_form = None
    title = _(u"Bulk view") if not references_list else _(u"List view of %s") % verbose_listname
    return render_to_response("bulk.html", {"title": title, "references": references,
                                            "prev_link": prev_link, "next_link": next_link, "pages": pages,
                                            "add_to_shelf": add_to_shelf_form, "export": export_form,
                                            "add_to_list": add_to_list_form,
                                            "remove_from_list": remove_from_list_form, "global_dummy": global_dummy_form},
                              context_instance=RequestContext(request))
