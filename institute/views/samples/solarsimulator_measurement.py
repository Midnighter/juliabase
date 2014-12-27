#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# This file is part of JuliaBase, the samples database.
#
# Copyright © 2008–2014 Forschungszentrum Jülich, Germany,
#                       Marvin Goblet <m.goblet@fz-juelich.de>,
#                       Torsten Bronger <t.bronger@fz-juelich.de>
#
# You must not use, install, pass on, offer, sell, analyse, modify, or
# distribute this software without explicit permission of the copyright holder.
# If you have received a copy of this software without the explicit permission
# of the copyright holder, you must destroy it immediately and completely.


from __future__ import absolute_import, unicode_literals

import datetime
from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.utils.translation import ugettext as _, ugettext_lazy
from jb_common.utils import is_json_requested, \
    respond_in_json
from samples import permissions
from samples.views import utils, feed_utils, form_utils as samples_form_utils
from institute.models import SolarsimulatorMeasurement, SolarsimulatorCellMeasurement
import institute.utils.views as form_utils


class SolarsimulatorMeasurementForm(samples_form_utils.ProcessForm):

    class Meta:
        model = SolarsimulatorMeasurement
        fields = "__all__"

    def __init__(self, user, *args, **kwargs):
        super(SolarsimulatorMeasurementForm, self).__init__(user, *args, **kwargs)
        self.fields["temperature"].widget.attrs.update({"size": "5"})


class SolarsimulatorCellForm(forms.ModelForm):

    class Meta:
        model = SolarsimulatorCellMeasurement
        exclude = ("measurement",)

    def __init__(self, *args, **kwargs):
        super(SolarsimulatorCellForm, self).__init__(*args, **kwargs)

    def validate_unique(self):
        pass


def solarsimulator_cell_forms_from_post(post, form_cls):
    """This function initializes the solarsimulator cell forms from the post data.
    It also decides which kind of cell forms is needed.

    :param post: the post dictionary

    :type post: QueryDict

    :return:
      a list of bound solarsimulator cell forms or solarsimulator dark cell
      forms

    :rtype: list
    """
    indices = samples_form_utils.collect_subform_indices(post)
    return [form_cls(post, prefix=str(measurement_index)) for measurement_index in indices]


def is_all_valid(solarsimulator_measurement_form, sample_form, remove_from_my_samples_form, edit_description_form,
                 solarsimulator_cell_forms):
    """Tests the “inner” validity of all forms belonging to this view.  This
    function calls the ``is_valid()`` method of all forms, even if one of them
    returns ``False`` (and makes the return value clear prematurely).

    :param solarsimulator_measurement_form: a bound solarsimulator measurement form
    :param sample_form: a bound sample selection form
    :param remove_from_my_samples_form: a bound remove-from-my-samples form
    :param edit_description_form: a bound edit-description form
    :param solarsimulator_cell_forms: a list of bound solarsimulator cell forms

    :type solarsimulator_measurement_form: `SolarsimulatorMeasurementForm`
    :type sample_form: `samples.views.form_utils.SampleSelectForm`
    :type remove_from_my_samples_form:
        `samples.views.form_utils.RemoveFromMySamplesForm` or NoneType
    :type edit_description_form: `samples.views.form_utils.EditDescriptionForm`
    :type solarsimulator_cell_forms: `SolarsimulatorCellForm`

    :return:
      whether all forms are valid, i.e. their ``is_valid`` method returns
      ``True``.

    :rtype: bool
    """
    all_valid = solarsimulator_measurement_form.is_valid()
    all_valid = sample_form.is_valid() and all_valid
    if remove_from_my_samples_form:
        all_valid = remove_from_my_samples_form.is_valid() and all_valid
    if edit_description_form:
        all_valid = edit_description_form.is_valid() and all_valid
    if solarsimulator_cell_forms:
        all_valid = all([solarsimulator_cell_form.is_valid()
                         for solarsimulator_cell_form in solarsimulator_cell_forms]) and all_valid
    return all_valid


def is_referentially_valid(solarsimulator_measurement_form, solarsimulator_cell_forms, sample_form, process_id=None):
    """Test whether the forms are consistent with each other and with the
    database.  In particular, it tests whether the sample is still “alive” at
    the time of the measurement and whether the related data file exists.

    FixMe: It does not check for the case that the same datapath is used in two
    different solarsimulator measurements.  This should be added.  One may call
    :py:func:`institute.views.samples.json_client._get_solarsimulator_measurement_by_filepath`
    and catch an exception about multiple search results for checking this.

    :return:
      whether the forms are consistent with each other and the database

    :rtype: bool
    """
    referentially_valid = solarsimulator_measurement_form.is_referentially_valid(sample_form)
    if not solarsimulator_cell_forms:
        solarsimulator_measurement_form.add_error(None, _("No measurenents given."))
        referentially_valid = False
    if solarsimulator_measurement_form.is_valid():
        positions = set()
        for measurement_form in solarsimulator_cell_forms:
            if measurement_form.is_valid():
                data_file = measurement_form.cleaned_data["data_file"]
                position = measurement_form.cleaned_data["position"]
                if position in positions:
                    measurement_form.add_error(None, _("This cell position is already given."))
                    referentially_valid = False
                else:
                    positions.add(position)
    else:
        referentially_valid = False
    return referentially_valid


@login_required
def edit(request, solarsimulator_measurement_id):
    """Create or edit an existing solarsimulator measurement.

    If you pass ``only_single_cell_added=true`` in the query string *and* you
    have a staff account, no feed entries are generated.  This is to make the
    solarsimulator crawler less noisy if non-standard-Jülich cell layout is
    used and a whole substrate is split over many single files which have to be
    imported one by one.

    :param request: the current HTTP Request object
    :param solarsimulator_measurement_id: the id of the solarsimulator
        measurement; if ``None``, a new measurement is created

    :type request: HttpRequest
    :type solarsimulator_measurement_id: unicode

    :return:
      the HTTP response object

    :rtype: HttpResponse
    """
    solarsimulator_measurement = get_object_or_404(SolarsimulatorMeasurement, id=solarsimulator_measurement_id)\
        if solarsimulator_measurement_id is not None else None
    permissions.assert_can_add_edit_physical_process(request.user, solarsimulator_measurement,
                                                     SolarsimulatorMeasurement)
    preset_sample = utils.extract_preset_sample(request) if not solarsimulator_measurement else None
    if request.method == "POST":
        sample_form = samples_form_utils.SampleSelectForm(request.user, solarsimulator_measurement, preset_sample, request.POST)
        samples = solarsimulator_measurement.samples.all() if solarsimulator_measurement else None
        remove_from_my_samples_form = samples_form_utils.RemoveFromMySamplesForm(request.POST) if not solarsimulator_measurement \
            else None
        edit_description_form = samples_form_utils.EditDescriptionForm(request.POST) if solarsimulator_measurement else None
        solarsimulator_cell_forms = solarsimulator_cell_forms_from_post(request.POST, SolarsimulatorCellForm)
        solarsimulator_measurement_form = SolarsimulatorMeasurementForm(request.user, request.POST,
                                                                        instance=solarsimulator_measurement)
        all_valid = is_all_valid(solarsimulator_measurement_form, sample_form, remove_from_my_samples_form,
                                 edit_description_form, solarsimulator_cell_forms)
        referentially_valid = is_referentially_valid(solarsimulator_measurement_form,
                                                     solarsimulator_cell_forms, sample_form, solarsimulator_measurement_id)
        if all_valid and referentially_valid:
            solarsimulator_measurement = solarsimulator_measurement_form.save()
            samples = [sample_form.cleaned_data["sample"]]
            solarsimulator_measurement.samples = samples
            solarsimulator_measurement.cells.all().delete()
            for solarsimulator_cell_form in solarsimulator_cell_forms:
                solarsimulator_cell_measurement = solarsimulator_cell_form.save(commit=False)
                solarsimulator_cell_measurement.measurement = solarsimulator_measurement
                solarsimulator_cell_measurement.save()
            if not request.user.is_staff or request.GET.get("only_single_cell_added") != "true":
                reporter = request.user if not request.user.is_staff \
                    else solarsimulator_measurement_form.cleaned_data["operator"]
                feed_utils.Reporter(reporter).report_physical_process(
                    solarsimulator_measurement, edit_description_form.cleaned_data if edit_description_form else None)
            if remove_from_my_samples_form and remove_from_my_samples_form.cleaned_data["remove_from_my_samples"]:
                utils.remove_samples_from_my_samples(samples, request.user)
            success_report = _(u"{process} was successfully changed in the database."). \
                format(process=solarsimulator_measurement) \
                if solarsimulator_measurement_id else _(u"{process} was successfully added to the database."). \
                format(process=solarsimulator_measurement)
            return utils.successful_response(request, success_report, json_response=solarsimulator_measurement.pk)
    else:
        solarsimulator_measurement_form = SolarsimulatorMeasurementForm(request.user, instance=solarsimulator_measurement)
        initial = {}
        solarsimulator_cell_forms = []
        if solarsimulator_measurement:
            samples = solarsimulator_measurement.samples.all()
            if samples:
                initial["sample"] = samples[0].pk
            solarsimulator_cell_forms = \
                [SolarsimulatorCellForm(prefix=str(index), instance=solarsimulator_cell)
                 for index, solarsimulator_cell in enumerate(solarsimulator_measurement.cells.all())]
        sample_form = samples_form_utils.SampleSelectForm(request.user, solarsimulator_measurement, preset_sample, initial=initial)
        remove_from_my_samples_form = samples_form_utils.RemoveFromMySamplesForm() if not solarsimulator_measurement else None
        edit_description_form = samples_form_utils.EditDescriptionForm() if solarsimulator_measurement else None
    title = _(u"{name} of {sample}").format(name=SolarsimulatorMeasurement._meta.verbose_name,
                                                        sample=samples[0]) if solarsimulator_measurement \
        else _(u"Add {name}").format(name=SolarsimulatorMeasurement._meta.verbose_name)
    return render(request, "samples/edit_solarsimulator_measurement.html",
                  {"title": title,
                   "solarsimulator_measurement": solarsimulator_measurement_form,
                   "solarsimulator_cell_measurements": solarsimulator_cell_forms,
                   "sample": sample_form,
                   "remove_from_my_samples": remove_from_my_samples_form,
                   "edit_description": edit_description_form})
