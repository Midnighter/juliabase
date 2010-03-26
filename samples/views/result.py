#!/usr/bin/env python
# -*- coding: utf-8 -*-

u"""Views for editing and creating results (aka result processes).
"""

from __future__ import absolute_import

import datetime, os, shutil, re
from django.template import RequestContext
from django.http import Http404
import django.forms as forms
from django.shortcuts import render_to_response, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.translation import ugettext as _, ugettext_lazy
from django.db.models import Q
import chantal_common.utils
from chantal_common.utils import append_error
from samples import models, permissions
from samples.views import utils, form_utils, feed_utils, csv_export


def save_image_file(image_data, result, related_data_form):
    u"""Saves an uploaded image file stream to its final destination in
    `settings.UPLOADED_RESULT_IMAGES_ROOT`.  If the given result has already an
    image connected with it, it is removed first.

    :Parameters:
      - `image_data`: the file-like object which contains the uploaded data
        stream
      - `result`: The result object for which the image was uploaded.  It is
        not necessary that all its fields are already there.  But it must have
        been written already to the database because the only necessary field
        is the primary key, which I need for the hash digest for generating the
        file names.
      - `related_data_form`: A bound form with the image filename that was
        uploaded.  This is only needed to dumping error messages into it if
        something went wrong.

    :type image_data: ``django.core.files.uploadedfile.UploadedFile``
    :type result: `models.Result`
    :type related_data_form: `RelatedDataForm`
    """
    for i, chunk in enumerate(image_data.chunks()):
        if i == 0:
            if chunk.startswith("\211PNG\r\n\032\n"):
                new_image_type = "png"
            elif chunk.startswith("\xff\xd8\xff"):
                new_image_type = "jpeg"
            elif chunk.startswith("%PDF"):
                new_image_type = "pdf"
            else:
                append_error(related_data_form, _(u"Invalid file format.  Only PDF, PNG, and JPEG are allowed."),
                             "image_file")
                return
            if result.image_type != "none" and new_image_type != result.image_type:
                os.remove(result.get_image_locations()["original"])
            result.image_type = new_image_type
            image_locations = result.get_image_locations()
            shutil.rmtree(image_locations["image_directory"], ignore_errors=True)
            destination = open(image_locations["original"], "wb+")
        destination.write(chunk)
    destination.close()
    result.save()


class ResultForm(form_utils.ProcessForm):
    u"""Model form for a result process.  Note that I exclude many fields
    because they are not used in results or explicitly set.

    FixMe: Possibly, the external operator should be made editable for result
    processes.
    """
    _ = ugettext_lazy

    def __init__(self, *args, **kwargs):
        super(ResultForm, self).__init__(*args, **kwargs)
        self.fields["comments"].required = True
        self.fields["title"].widget.attrs["size"] = 40

    class Meta:
        model = models.Result
        exclude = ("timestamp", "timestamp_inaccuracy", "operator", "external_operator", "image_type",
                   "quantities_and_values")


class RelatedDataForm(forms.Form):
    u"""Form for samples, sample series, and the image connected with this
    result process.  Since all these things are not part of the result process
    model itself, they are in a form of its own.
    """
    _ = ugettext_lazy
    samples = form_utils.MultipleSamplesField(label=_(u"Samples"), required=False)
    sample_series = forms.ModelMultipleChoiceField(label=_(u"Sample serieses"), queryset=None, required=False)
    image_file = forms.FileField(label=_(u"Image file"), required=False)

    def __init__(self, user_details, query_string_dict, old_result, data=None, files=None, **kwargs):
        u"""Form constructor.  I have to initialise a couple of things here in
        a non-trivial way.

        The most complicated thing is to find all sample series electable for
        the result.  Note that the current query will probably find to many
        electable sample series, but unallowed series will be rejected by
        `clean` anyway.
        """
        super(RelatedDataForm, self).__init__(data, files, **kwargs)
        self.old_relationships = set(old_result.samples.all()) | set(old_result.sample_series.all()) if old_result else set()
        self.user = user_details.user
        now = datetime.datetime.now() + datetime.timedelta(seconds=5)
        three_months_ago = now - datetime.timedelta(days=90)
        samples = list(user_details.my_samples.all())
        if old_result:
            samples.extend(old_result.samples.all())
            self.fields["sample_series"].queryset = \
                models.SampleSeries.objects.filter(
                Q(samples__watchers=user_details) | ( Q(currently_responsible_person=user_details.user) &
                                                      Q(timestamp__range=(three_months_ago, now)))
                | Q(pk__in=old_result.sample_series.values_list("pk", flat=True))).distinct()
            self.fields["samples"].initial = old_result.samples.values_list("pk", flat=True)
            self.fields["sample_series"].initial = old_result.sample_series.values_list("pk", flat=True)
        else:
            if "sample" in query_string_dict:
                preset_sample = get_object_or_404(models.Sample, name=query_string_dict["sample"])
                self.fields["samples"].initial = [preset_sample.pk]
                samples.append(preset_sample)
            self.fields["sample_series"].queryset = \
                models.SampleSeries.objects.filter(Q(samples__watchers=user_details) |
                                                   ( Q(currently_responsible_person=user_details.user) &
                                                     Q(timestamp__range=(three_months_ago, now)))
                                                   | Q(name=query_string_dict.get("sample_series", u""))).distinct()
            if "sample_series" in query_string_dict:
                self.fields["sample_series"].initial = \
                    [get_object_or_404(models.SampleSeries, name=query_string_dict["sample_series"])]
        self.fields["samples"].set_samples(samples)
        self.fields["image_file"].widget.attrs["size"] = 60

    def clean(self):
        u"""Global clean method for the related data.  I check whether at least
        one sample or sample series was selected, and whether the user is
        allowed to add results to the selected objects.
        """
        samples = self.cleaned_data.get("samples")
        sample_series = self.cleaned_data.get("sample_series")
        if samples is not None and sample_series is not None:
            for sample_or_series in set(samples + sample_series) - self.old_relationships:
                if not permissions.has_permission_to_add_result_process(self.user, sample_or_series):
                    append_error(self, _(u"You don't have the permission to add the result to all selected samples/series."))
            if not samples and not sample_series:
                append_error(self, _(u"You must select at least one samples/series."))
        return self.cleaned_data


class DimensionsForm(forms.Form):
    u"""Model form for the number of quantities and values per quantity in the
    result values table.  In other words, it is the number or columns
    (``number_of_quantities``) and the number or rows (``number_of_values``) in
    this table.

    This form class is also used for the hidden ``previous_dimensions_form``.
    It contains the values set *before* the user made his input.  Thus, one can
    decide easily whether the user has changed something, plus one can easily
    read-in the table value given by the user.  (The table had the previous
    dimensions after all.)
    """
    _ = ugettext_lazy
    number_of_quantities = forms.IntegerField(label=_(u"Number of quantities"), min_value=0, max_value=100)
    number_of_values = forms.IntegerField(label=_(u"Number of values"), min_value=0, max_value=100)

    def __init__(self, *args, **kwargs):
        super(DimensionsForm, self).__init__(*args, **kwargs)
        self.fields["number_of_quantities"].widget.attrs.update({"size": 1, "style": "text-align: center"})
        self.fields["number_of_values"].widget.attrs.update({"size": 1, "style": "text-align: center"})

    def clean(self):
        u"""If one of the two dimensions is set to zero, the other is set to
        zero, too.
        """
        cleaned_data = self.cleaned_data
        if "number_of_quantities" in cleaned_data and "number_of_values" in cleaned_data:
            if cleaned_data["number_of_quantities"] == 0 or cleaned_data["number_of_values"] == 0:
                cleaned_data["number_of_quantities"] = cleaned_data["number_of_values"] = 0
        return cleaned_data


class QuantityForm(forms.Form):
    u"""Form for one quantity field (i.e., one heading in the result values
    table).  All HTML entities in it are immediately converted to their unicode
    pendant (i.e., the conversion is not delayed until display, as with
    Markdown content).  Furthermore, all whitespace is normalised.
    """
    _ = ugettext_lazy
    quantity = forms.CharField(label=_("Quantity name"), max_length=50)

    def __init__(self, *args, **kwargs):
        super(QuantityForm, self).__init__(*args, **kwargs)
        self.fields["quantity"].widget.attrs.update({"size": 10, "style": "font-weight: bold; text-align: center"})

    def clean_quantity(self):
        quantity = u" ".join(self.cleaned_data["quantity"].split())
        return chantal_common.utils.substitute_html_entities(quantity)


class ValueForm(forms.Form):
    u"""Form for one value entry in the result values table.  Note that this is
    a pure unicode field and not a number field, so you may enter whatever you
    like here.  Whitespace is not normalised, and no other conversion takes
    place.
    """
    _ = ugettext_lazy
    value = forms.CharField(label=_("Value"), max_length=50, required=False)

    def __init__(self, *args, **kwargs):
        super(ValueForm, self).__init__(*args, **kwargs)
        self.fields["value"].widget.attrs.update({"size": 10})


class FormSet(object):
    u"""Class for holding all forms of the result views, and for all methods
    working on these forms.  The main advantage of putting all this into a big
    class is to avoid long parameter and return tuples because one can use
    instance attributes instead.

    :ivar result: the result to be edited.  If it is ``None``, we create a new
      one.  This is very important because testing ``result`` is the only way
      to distinguish between editing or creating.

    :ivar result_form: the form with the result process
      
    :ivar related_data_form: the form with all samples and sample series the
      result should be connected with

    :ivar dimensions_form: the form with the number of columns and rows in the
      result values table

    :ivar previous_dimonesions_form: the form with the number of columns and
      rows from the previous view, in order to see whether they were changed

    :ivar quantity_forms: The (mostly) bound forms of quantities (the column
      heads in the table).  Those that are newly added are unbound.  (In case
      of a GET method, all are unbound of course.)

    :ivar value_form_lists: The (mostly) bound forms of result values in the
      table.  Those that are newly added are unbound.  The outer list are the
      rows, the inner the columns.  (In case of a GET method, all are unbound
      of course.)

    :ivar edit_description_form: the bound form with the edit description if
      we're editing an existing result, and ``None`` otherwise

    :type result: `models.Result` or ``NoneType``
    :type result_form: `ResultForm`
    :type related_data_form: `RelatedDataForm`
    :type dimensions_form: `DimensionsForm`
    :type previous_dimensions_form: `DimensionsForm`
    :type quantity_forms: list of `QuantityForm`
    :type value_form_lists: list of list of `ValueForm`
    :type edit_description_form: `form_utils.EditDescriptionForm` or
      ``NoneType``
    """

    def __init__(self, request, process_id):
        u"""Class constructor.
        
        :Parameters:
          - `request`: the current HTTP Request object
          - `process_id`: the ID of the result to be edited; ``None`` if we
            create a new one

        :type request: ``HttpRequest``
        :type process_id: unicode or ``NoneType``
        """
        self.result = get_object_or_404(models.Result, pk=utils.convert_id_to_int(process_id)) if process_id else None
        self.user_details = utils.get_profile(request.user)
        self.query_string_dict = utils.parse_query_string(request) if not self.result else None

    def from_database(self):
        u"""Generate all forms from the database.  This is called when the HTTP
        GET method was sent with the request.
        """
        self.result_form = ResultForm(instance=self.result)
        self.related_data_form = RelatedDataForm(self.user_details, self.query_string_dict, self.result)
        self.edit_description_form = form_utils.EditDescriptionForm() if self.result else None
        if self.result and self.result.quantities_and_values:
            quantities, values = utils.ascii_unpickle(self.result.quantities_and_values)
        else:
            quantities, values = [], []
        self.dimensions_form = DimensionsForm(initial={"number_of_quantities": len(quantities),
                                                       "number_of_values": len(values)})
        self.quantity_forms = [QuantityForm(initial={"quantity": quantity}, prefix=str(i))
                               for i, quantity in enumerate(quantities)]
        self.value_form_lists = []
        for j, value_list in enumerate(values):
            self.value_form_lists.append([ValueForm(initial={"value": value}, prefix="%d_%d" % (i, j))
                                          for i, value in enumerate(value_list)])

    def from_post_data(self, post_data, post_files):
        u"""Generate all forms from the database.  This is called when the HTTP
        POST method was sent with the request.

        :Parameters:
          - `post_data`:  The post data submitted via HTTP.  It is the result
            of ``request.POST``.
          - `post_files`: The file data submitted via HTTP.  It is the result
            of ``request.FILES``.

        :type post_data: ``django.http.QueryDict``
        :type post_files: ``django.utils.datastructures.MultiValueDict``
        """
        self.result_form = ResultForm(post_data, instance=self.result)
        self.related_data_form = \
            RelatedDataForm(self.user_details, self.query_string_dict, self.result, post_data, post_files)
        self.dimensions_form = DimensionsForm(post_data)
        self.previous_dimensions_form = DimensionsForm(post_data, prefix="previous")
        if self.previous_dimensions_form.is_valid():
            found_number_of_quantities = self.previous_dimensions_form.cleaned_data["number_of_quantities"]
            found_number_of_values = self.previous_dimensions_form.cleaned_data["number_of_values"]
        else:
            found_number_of_quantities, found_number_of_values = 0, 0
        if self.dimensions_form.is_valid():
            number_of_quantities = self.dimensions_form.cleaned_data["number_of_quantities"]
            number_of_values = self.dimensions_form.cleaned_data["number_of_values"]
            found_number_of_quantities = min(found_number_of_quantities, number_of_quantities)
            found_number_of_values = min(found_number_of_values, number_of_values)
        else:
            number_of_quantities, number_of_values = found_number_of_quantities, found_number_of_values
        self.quantity_forms = []
        for i in range(number_of_quantities):
            self.quantity_forms.append(
                QuantityForm(post_data, prefix=str(i)) if i < found_number_of_quantities else QuantityForm(prefix=str(i)))
        self.value_form_lists = []
        for j in range(number_of_values):
            values = []
            for i in range(number_of_quantities):
                if i < found_number_of_quantities and j < found_number_of_values:
                    values.append(ValueForm(post_data, prefix="%d_%d" % (i, j)))
                else:
                    values.append(ValueForm(prefix="%d_%d" % (i, j)))
            self.value_form_lists.append(values)
        self.edit_description_form = form_utils.EditDescriptionForm(post_data) if self.result else None

    def _is_all_valid(self):
        u"""Test whether all bound forms are valid.  This routine guarantees that
        all ``is_valid()`` methods are called, even if the first tested form is
        already invalid.

        :Return:
          whether all forms are valid

        :rtype: bool
        """
        all_valid = self.result_form.is_valid()
        all_valid = self.related_data_form.is_valid() and all_valid
        all_valid = self.dimensions_form.is_valid() and all_valid
        all_valid = self.previous_dimensions_form.is_valid() and all_valid
        all_valid = all([form.is_valid() for form in self.quantity_forms]) and all_valid
        all_valid = all([all([form.is_valid() for form in form_list]) for form_list in self.value_form_lists]) and all_valid
        if self.edit_description_form:
            all_valid = self.edit_description_form.is_valid() and all_valid
        return all_valid

    def _is_referentially_valid(self):
        u"""Test whether all forms are consistent with each other and with the
        database.  In particular, I test here whether the “important” checkbox
        in marked if the user has added new samples or sample series to the
        result.  I also assure that no two quantities in the result table
        (i.e., the column headings) are the same.

        :Return:
          whether all forms are consistent with each other and the database

        :rtype: bool
        """
        referentially_valid = True
        if self.result and self.related_data_form.is_valid() and self.edit_description_form.is_valid():
            old_related_objects = set(self.result.samples.all()) | set(self.result.sample_series.all())
            new_related_objects = set(self.related_data_form.cleaned_data["samples"] +
                                      self.related_data_form.cleaned_data["sample_series"])
            if new_related_objects - old_related_objects and not self.edit_description_form.cleaned_data["important"]:
                append_error(self.edit_description_form, _(u"Adding samples or sample series must be marked as important."),
                             "important")
                referentially_valid = False
        quantities = set()
        for quantity_form in self.quantity_forms:
            if quantity_form.is_valid():
                quantity = quantity_form.cleaned_data["quantity"]
                if quantity in quantities:
                    append_error(quantity_form, _(u"This quantity is already used in this table."), "quantity")
                else:
                    quantities.add(quantity)
        return referentially_valid

    def _is_structure_changed(self):
        u"""Check whether the structure was changed by the user, i.e. whether
        the table dimensions were changed.  (In this case, the view has to be
        re-displayed instead of being written to the database.)

        :Return:
          whether the dimensions of the result values table were changed

        :rtype: bool
        """
        if self.dimensions_form.is_valid() and self.previous_dimensions_form.is_valid():
            return self.dimensions_form.cleaned_data["number_of_quantities"] != \
                self.previous_dimensions_form.cleaned_data["number_of_quantities"] or \
                self.dimensions_form.cleaned_data["number_of_values"] != \
                self.previous_dimensions_form.cleaned_data["number_of_values"]
        else:
            # In case of doubt, assume that the structure was changed.
            # Actually, this should never happen unless the browser is broken.
            return True

    def serialize_quantities_and_values(self):
        u"""Serialise the result table data (quantities and values) to a string
        which is ready to be written to the database.  See the
        ``quantities_and_values`` attribute of `samples.models.Result` for
        further information.

        :Return:
          the serialised result values table, as an ASCII-only string

        :rtype: str
        """
        result = [form.cleaned_data["quantity"] for form in self.quantity_forms], \
            [[form.cleaned_data["value"] for form in form_list] for form_list in self.value_form_lists]
        return utils.ascii_pickle(result)

    def save_to_database(self, post_files):
        u"""Save the forms to the database.  One peculiarity here is that I
        still check validity on this routine, namely whether the uploaded image
        data is correct.  If it is not, the error is written to the
        ``result_form`` and the result of this routine is ``None``.  I also
        check all other types of validity, and whether the structure was
        changed (i.e., the dimensions of the result values table were changed).

        :Parameters:
          - `post_files`: The file data submitted via HTTP.  It is the result
            of ``request.FILES``.

        :type post_files: ``django.utils.datastructures.MultiValueDict``

        :Return:
          the created or updated result instance, or ``None`` if the data
          couldn't yet be written to the database, but the view has to be
          re-displayed

        :rtype: `models.Result` or ``NoneType``
        """
        all_valid = self._is_all_valid()
        referentially_valid = self._is_referentially_valid()
        structure_changed = self._is_structure_changed()
        if all_valid and referentially_valid and not structure_changed:
            # FixMe: Maybe upload file first, and make a successful upload the
            # forth precondition for this branch?
            if self.result:
                result = self.result_form.save()
            else:
                result = self.result_form.save(commit=False)
                result.operator = self.user_details.user
                result.timestamp = datetime.datetime.now()
            result.quantities_and_values = self.serialize_quantities_and_values()
            result.save()
            if self.related_data_form.cleaned_data["image_file"]:
                save_image_file(post_files["image_file"], result, self.related_data_form)
            if self.related_data_form.is_valid():
                result.samples = self.related_data_form.cleaned_data["samples"]
                result.sample_series = self.related_data_form.cleaned_data["sample_series"]
                return result

    def update_previous_dimensions_form(self):
        u"""Set the form with the previous dimensions to the currently set
        dimensions.
        """
        self.previous_dimensions_form = DimensionsForm(
            initial={"number_of_quantities": len(self.quantity_forms), "number_of_values": len(self.value_form_lists)},
                     prefix="previous")

    def get_context_dict(self):
        u"""Retrieve the context dictionary to be passed to the template.  This
        context dictionary contains all forms in an easy-to-use format for the
        template code.

        :Return:
          context dictionary

        :rtype: dict mapping str to various types
        """
        return {"result": self.result_form, "related_data": self.related_data_form,
                "edit_description": self.edit_description_form, "dimensions": self.dimensions_form,
                "previous_dimensions": self.previous_dimensions_form, "quantities": self.quantity_forms,
                "value_lists": self.value_form_lists}


@login_required
def edit(request, process_id):
    u"""View for editing existing results, and for creating new ones.

    :Parameters:
      - `request`: the current HTTP Request object
      - `process_id`: the ID of the result process; ``None`` if we're creating
        a new one

    :type request: ``HttpRequest``
    :type process_id: str

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    form_set = FormSet(request, process_id)
    if form_set.result:
        permissions.assert_can_edit_result_process(request.user, form_set.result)
    if request.method == "POST":
        form_set.from_post_data(request.POST, request.FILES)
        result = form_set.save_to_database(request.FILES)
        if result:
            feed_utils.Reporter(request.user).report_result_process(
                result, form_set.edit_description_form.cleaned_data if form_set.edit_description_form else None)
            return utils.successful_response(request)
    else:
        form_set.from_database()
    form_set.update_previous_dimensions_form()
    title = _(u"Edit result") if form_set.result else _(u"New result")
    context_dict = {"title": title}
    context_dict.update(form_set.get_context_dict())
    return render_to_response("samples/edit_result.html", context_dict, context_instance=RequestContext(request))


@login_required
def show(request, process_id):
    u"""Shows a particular result process.  The main purpose of this view is to
    be able to visit a result directly from a feed entry about a new/edited
    result.

    :Parameters:
      - `request`: the current HTTP Request object
      - `process_id`: the database ID of the result to show

    :type request: ``HttpRequest``
    :type process_id: unicode

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    result = get_object_or_404(models.Result, pk=utils.convert_id_to_int(process_id))
    permissions.assert_can_view_result_process(request.user, result)
    template_context = {"title": _(u"Result “%s”") % result.title, "result": result,
                        "samples": result.samples.all(), "sample_series": result.sample_series.all()}
    template_context.update(utils.ResultContext(request.user, sample_series=None).digest_process(result))
    return render_to_response("samples/show_single_result.html", template_context, context_instance=RequestContext(request))


@login_required
def export(request, process_id):
    u"""View for exporting a result process to CSV data.  Thus, the return
    value is not an HTML response but a text/csv response.

    :Parameters:
      - `request`: the current HTTP Request object
      - `process_id`: the database ID of the result to show

    :type request: ``HttpRequest``
    :type process_id: unicode

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    result = get_object_or_404(models.Result, pk=utils.convert_id_to_int(process_id))
    permissions.assert_can_view_result_process(request.user, result)
    # Translation hint: In a table
    return csv_export.export(request, result.get_data(), _(u"row"))