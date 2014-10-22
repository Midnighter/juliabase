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

"""The view for merging samples together.
"""

from __future__ import absolute_import, unicode_literals

from django.utils.translation import ugettext as _, ugettext_lazy
from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.forms.util import ValidationError
from jb_common.utils import append_error
from samples import models
from samples.views import utils
from samples.views import form_utils
import settings
from django.core.urlresolvers import get_callable


class MergeSamplesForm(forms.Form):
    """The merge samples form class.
    """
    _ = ugettext_lazy
    from_sample = form_utils.SampleField(label=_("merge sample"), required=False)
    to_sample = form_utils.SampleField(label=_("into sample"), required=False)

    def __init__(self, user, my_samples, *args, **kwargs):
        super(MergeSamplesForm, self).__init__(*args, **kwargs)
        self.user = user
        self.fields["from_sample"].set_samples(my_samples, user)
        self.fields["to_sample"].set_samples(my_samples, user)

    def clean_from_sample(self):
        from_sample = self.cleaned_data["from_sample"]
        if from_sample and (from_sample.split_origin or models.SampleSplit.objects.filter(parent=from_sample).exists()
                            or models.SampleDeath.objects.filter(samples=from_sample).exists()):
            raise ValidationError(
                _("It is not possible to merge a sample that was split, killed, or is the result of a sample split."))
        return from_sample

    def clean(self):
        def get_first_process(sample, process_cls):
            try:
                return process_cls.objects.filter(samples=sample)[0]
            except IndexError:
                return None

        cleaned_data = self.cleaned_data
        from_sample = cleaned_data.get("from_sample")
        to_sample = cleaned_data.get("to_sample")
        if from_sample and not to_sample:
            append_error(self, _("You must select a target sample."))
        elif not from_sample and to_sample:
            append_error(self, _("You must select a source sample."))
        elif from_sample and to_sample:
            if not (from_sample.currently_responsible_person == to_sample.currently_responsible_person == self.user) \
                    and not self.user.is_staff:
                append_error(self, _("You must be the currently responsible person of both samples."))
                cleaned_data.pop(from_sample, None)
                cleaned_data.pop(to_sample, None)
            if from_sample == to_sample:
                append_error(self, _("You can't merge a sample into itself."))
                cleaned_data.pop(from_sample, None)
                cleaned_data.pop(to_sample, None)
            sample_death = get_first_process(to_sample, models.SampleDeath)
            sample_split = get_first_process(to_sample, models.SampleSplit)
            if sample_death or sample_split:
                try:
                    latest_process = from_sample.processes.all().reverse()[0]
                except IndexError:
                    pass
                else:
                    if sample_death and sample_death.timestamp <= latest_process.timestamp:
                        append_error(self, _("One or more processes would be after sample death of {to_sample}.").format(
                                to_sample=to_sample.name))
                        cleaned_data.pop(from_sample, None)
                    if sample_split and sample_split.timestamp <= latest_process.timestamp:
                        append_error(self, _("One or more processes would be after sample split of {to_sample}.").format(
                                to_sample=to_sample.name))
                        cleaned_data.pop(from_sample, None)
        return cleaned_data


def merge_samples(from_sample, to_sample):
    """Copies all processes from one sample to another sample.
    The fist sample will be erased afterwards.

    :Parameters:
     - `from_sample`: The sample, who is merged into the other sample
     - `to_sample`: The sample, who should contains the processes from the other sample

    :type from_sample: `models.Sample`
    :type to_sample: `models.Sample`
    """
    current_sample = to_sample
    for process in from_sample.processes.order_by("-timestamp"):
        if current_sample.split_origin and current_sample.split_origin.timestamp > process.timestamp:
            current_sample = current_sample.split_origin.parent
        current_sample.processes.add(process)
    to_sample.series.add(*from_sample.series.all())
    to_aliases = set(alias.name for alias in to_sample.aliases.all())
    to_sample.aliases.add(*(alias for alias in from_sample.aliases.all() if alias.name not in to_aliases))
    if not to_sample.aliases.filter(name=from_sample.name).exists():
        to_sample.aliases.create(name=from_sample.name)
    try:
        cleanup_after_merge = get_callable(settings.MERGE_CLEANUP_FUNCTION)
    except (ImportError, AttributeError):
        pass
    else:
        cleanup_after_merge(from_sample, to_sample)
    from_sample.delete()

def is_referentially_valid(merge_samples_forms):
    """Test whether all forms are consistent with each other.

    :Parameters:
      - `merge_samples_forms`: all “merge samples forms”

    :type new_name_forms: list of `MergeSamplesForm`

    :Return:
      whether all forms are consistent with each other

    :rtype: bool
    """
    referentially_valid = True
    from_samples = set()
    to_samples = set()
    for merge_samples_form in merge_samples_forms:
        if merge_samples_form.is_valid():
            from_sample = merge_samples_form.cleaned_data["from_sample"]
            to_sample = merge_samples_form.cleaned_data["to_sample"]
            if from_sample in from_samples or to_sample in from_samples:
                append_error(merge_samples_form, _("You can merge a sample only once."))
                referentially_valid = False
            if from_sample in to_samples:
                append_error(merge_samples_form,
                             _("You can't merge a sample which was merged shortly before.  Do this in a separate call."))
                referentially_valid = False
            if from_sample:
                from_samples.add(from_sample)
            if to_sample:
                to_samples.add(to_sample)
    if referentially_valid and all(merge_samples_form.is_valid() for merge_samples_form in merge_samples_forms) \
            and not from_samples:
        append_error(merge_samples_forms[0], _("No samples selected."))
        referentially_valid = False
    return referentially_valid


number_of_pairs = 6

@login_required
def merge(request):
    """The merging of the samples is handled in this function.
    It creates the necessary forms, initiates the merging
    and returns the ``HttpResponse`` to the web browser.

    :Parameters:
      - `request`: the current HTTP Request object

    :type request: ``HttpRequest``

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    my_samples = list(request.user.my_samples.all())
    if request.method == "POST":
        merge_samples_forms = [MergeSamplesForm(request.user, my_samples, request.POST, prefix=str(index))
                               for index in range(number_of_pairs)]
        all_valid = all([merge_samples_form.is_valid() for merge_samples_form in merge_samples_forms])
        referentially_valid = is_referentially_valid(merge_samples_forms)
        if all_valid and referentially_valid:
            for merge_samples_form in merge_samples_forms:
                from_sample = merge_samples_form.cleaned_data.get("from_sample")
                to_sample = merge_samples_form.cleaned_data.get("to_sample")
                if from_sample and to_sample:
                    merge_samples(from_sample, to_sample)
            return utils.successful_response(request, _("Samples were successfully merged."))
    else:
        merge_samples_forms = [MergeSamplesForm(request.user, my_samples, prefix=str(index))
                               for index in range(number_of_pairs)]
    return render_to_response("samples/merge_samples.html", {"title": _("Merge samples"),
                                                             "merge_forms": merge_samples_forms},
                              context_instance=RequestContext(request))
