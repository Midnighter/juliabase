#!/usr/bin/env python
# -*- coding: utf-8 -*-

u"""All views and helper routines directly connected with the 6-chamber
deposition.  This includes adding, editing, and viewing such processes.

In principle, you can copy the code here to iplement other deposition systems,
however, this is not implemented perfectly: If done again, *all* form data
should be organised in a real form instead of being hard-coded in the template.
Additionally, `DataModelForm` was a sub-optimal idea: Instead, their data
should be exported into forms of their own, so that I needn't rely on the
validity of the main forms.
"""

import re
from django.template import RequestContext
from django.shortcuts import render_to_response, get_object_or_404
from django.forms import ModelForm, Form
from django.forms.util import ValidationError
from django import forms
import django.core.urlresolvers
from django.contrib.auth.decorators import login_required
from chantal.samples.models import SixChamberDeposition, SixChamberLayer, SixChamberChannel
from chantal.samples import models
from chantal.samples.views import utils
from chantal.samples.views.utils import check_permission, DataModelForm
from django.utils.translation import ugettext as _, ugettext_lazy
from django.conf import settings
import django.contrib.auth.models
from django.db.models import Q

class RemoveFromMySamples(Form):
    u"""Form class for one single checkbox for removing deposited samples from
    “My Samples”.
    """
    _ = ugettext_lazy
    remove_deposited_from_my_samples = forms.BooleanField(label=_(u"Remove deposited samples from My Samples"),
                                                          required=False, initial=True)

class AddMyLayerForm(Form):
    u"""Form class for a choice field for appending nicknamed layers from “My
    Layers” to the current deposition.
    """
    _ = ugettext_lazy
    my_layer_to_be_added = forms.ChoiceField(label=_(u"Nickname of My Layer to be added"), required=False)
    def __init__(self, data=None, **keyw):
        user_details = keyw.pop("user_details")
        super(AddMyLayerForm, self).__init__(data, **keyw)
        self.fields["my_layer_to_be_added"].choices = utils.get_my_layers(user_details, SixChamberDeposition)

class DepositionForm(ModelForm):
    u"""Model form for the basic deposition data.
    """
    _ = ugettext_lazy
    sample_list = forms.ModelMultipleChoiceField(label=_(u"Samples"), queryset=None)
    operator = utils.OperatorChoiceField(label=_(u"Operator"), queryset=django.contrib.auth.models.User.objects.all())
    def __init__(self, user_details, data=None, **keyw):
        u"""Form constructor.  I have to initialise a couple of things here in
        a non-trivial way, especially those that I have added myself
        (``sample_list`` and ``operator``).
        """
        deposition = keyw.get("instance")
        initial = keyw.get("initial", {})
        if deposition:
            # Mark the samples of the deposition in the choise field
            initial.update({"sample_list": [sample._get_pk_val() for sample in deposition.samples.all()]})
        keyw["initial"] = initial
        super(DepositionForm, self).__init__(data, **keyw)
        # Connect the date/time fields with the JavaScript
        split_widget = forms.SplitDateTimeWidget()
        split_widget.widgets[0].attrs = {'class': 'vDateField'}
        split_widget.widgets[1].attrs = {'class': 'vTimeField'}
        self.fields["timestamp"].widget = split_widget
        self.fields["sample_list"].queryset = \
            models.Sample.objects.filter(Q(processes=deposition) | Q(watchers=user_details)).distinct() if deposition \
            else user_details.my_samples
        self.fields["sample_list"].widget.attrs.update({"size": "15", "style": "vertical-align: top"})
    def clean_sample_list(self):
        sample_list = list(set(self.cleaned_data["sample_list"]))
        if not sample_list:
            raise ValidationError(_(u"You must mark at least one sample."))
        return sample_list
    def save(self, *args, **keyw):
        u"""Additionally to the deposition itself, I must store the list of
        samples connected with the deposition."""
        deposition = super(DepositionForm, self).save(*args, **keyw)
        deposition.samples = self.cleaned_data["sample_list"]
        return deposition
    class Meta:
        model = SixChamberDeposition

class LayerForm(DataModelForm):
    u"""Model form for a 6-chamber layer."""
    def __init__(self, data=None, **keyw):
        u"""Model form constructor.  I do additional initialisation here, but
        very harmless: It's only about visual appearance and numerical limits.
        """
        super(LayerForm, self).__init__(data, **keyw)
        self.fields["number"].widget.attrs.update({"size": "2", "style": "text-align: center; font-size: xx-large"})
        self.fields["comments"].widget.attrs["cols"] = "30"
        for fieldname in ["pressure", "time", "substrate_electrode_distance", "transfer_in_chamber", "pre_heat",
                          "gas_pre_heat_gas", "gas_pre_heat_pressure", "gas_pre_heat_time", "heating_temperature",
                          "transfer_out_of_chamber", "plasma_start_power",
                          "deposition_frequency", "deposition_power", "base_pressure"]:
            self.fields[fieldname].widget.attrs["size"] = "10"
        for fieldname, min_value, max_value in [("deposition_frequency", 13, 150), ("plasma_start_power", 0, 1000),
                                                ("deposition_power", 0, 1000)]:
            self.fields[fieldname].min_value = min_value
            self.fields[fieldname].max_value = max_value
    def clean_chamber(self):
        # FixMe: Isn't this already tested by Django itself?
        if self.cleaned_data["chamber"] not in set([x[0] for x in models.six_chamber_chamber_choices]):
            raise ValidationError(_(u"Name is unknown."))
        return self.cleaned_data["chamber"]
    def clean_time(self):
        return utils.clean_time_field(self.cleaned_data["time"])
    def clean_pre_heat(self):
        return utils.clean_time_field(self.cleaned_data["pre_heat"])
    def clean_gas_pre_heat_time(self):
        return utils.clean_time_field(self.cleaned_data["gas_pre_heat_time"])
    def clean_pressure(self):
        return utils.clean_quantity_field(self.cleaned_data["pressure"], ["mTorr", "mbar"])
    def clean_gas_pre_heat_pressure(self):
        return utils.clean_quantity_field(self.cleaned_data["gas_pre_heat_pressure"], ["mTorr", "mbar"])
    class Meta:
        model = SixChamberLayer
        exclude = ("deposition",)

class ChannelForm(ModelForm):
    u"""Model form for channels in 6-chamber depositions."""
    def __init__(self, data=None, **keyw):
        u"""Model form constructor.  I do additional initialisation here, but
        very harmless: It's only about visual appearance.
        """
        super(ChannelForm, self).__init__(data, **keyw)
        self.fields["number"].widget = forms.TextInput(attrs={"size": "3", "style": "text-align: center"})
        self.fields["flow_rate"].widget = forms.TextInput(attrs={"size": "7"})
    def clean_gas(self):
        # FixMe: Isn't this already tested by Django itself?
        if self.cleaned_data["gas"] not in set([x[0] for x in models.six_chamber_gas_choices]):
            raise ValidationError(_(u"Gas type is unknown."))
        return self.cleaned_data["gas"]
    class Meta:
        model = SixChamberChannel
        exclude = ("layer",)

def is_all_valid(deposition_form, layer_forms, channel_form_lists, remove_from_my_samples_form):
    u"""Tests the “inner” validity of all forms belonging to this view.  This
    function calls the ``is_valid()`` method of all forms, even if one of them
    returns ``False`` (and makes the return value clear prematurely).

    Note that the validity of the ``add_my_layer_form`` is not checked – its
    contents is tested and used directly in `change_structure`.

    :Parameters:
      - `deposition_form`: a bound deposition form
      - `layer_forms`: the list with all bound layer forms of the deposition
      - `channel_form_lists`: all bound channel forms of this deposition.  It
        is a list, and every item is again a list containing all the channels
        of the layer with the same index in ``layer forms``.

    :type deposition_form: `DepositionForm`
    :type layer_forms: list of `LayerForm`
    :type channel_form_lists: list of lists of `ChannelForm`

    :Return:
      whether all forms are valid, i.e. their ``is_valid`` method returns
      ``True``.

    :rtype: bool
    """
    valid = deposition_form.is_valid() and remove_from_my_samples_form.is_valid()
    # Don't use a generator expression here because I want to call ``is_valid``
    # for every form
    valid = valid and all([layer_form.is_valid() for layer_form in layer_forms])
    for forms in channel_form_lists:
        valid = valid and all([channel_form.is_valid() for channel_form in forms])
    return valid

def change_structure(layer_forms, channel_form_lists, post_data):
    u"""Add or delete layers and channels in the form.  While changes in form
    fields are performs by the form objects themselves, they can't change the
    *structure* of the view.  This is performed here.
    
    :Parameters:
      - `layer_forms`: the list with all bound layer forms of the deposition
      - `channel_form_lists`: all bound channel forms of this deposition.  It
        is a list, and every item is again a list containing all the channels
        of the layer with the same index in ``layer forms``.
      - `post_data`: the result of ``request.POST``

    :type layer_forms: list of `LayerForm`
    :type channel_form_lists: list of lists of `ChannelForm`
    :type post_data: ``QueryDict``

    :Return:
      whether the structure was changed, i.e. whether layers/channels were
      add or deleted

    :rtype: bool
    """
    # Attention: `post_data` doesn't contain the normalised prefixes, so it
    # must not be used for anything except the `change_params`.  (The
    # structural-change prefixes needn't be normalised!)
    structure_changed = False
    change_params = dict([(key, post_data[key]) for key in post_data if key.startswith("structural-change-")])
    biggest_layer_number = max([utils.int_or_zero(layer.uncleaned_data("number")) for layer in layer_forms] + [0])
    new_layers = []
    new_channel_lists = []
    
    # First step: Duplicate layers
    for i, layer_form in enumerate(layer_forms):
        if layer_form.is_valid() and all([channel.is_valid() for channel in channel_form_lists[i]]) and \
                "structural-change-duplicate-layerindex-%d" % i in change_params:
            structure_changed = True
            layer_data = layer_form.cleaned_data
            layer_data["number"] = biggest_layer_number + 1
            biggest_layer_number += 1
            layer_index = len(layer_forms) + len(new_layers)
            new_layers.append(LayerForm(initial=layer_data, prefix=str(layer_index)))
            new_channel_lists.append(
                [ChannelForm(initial=channel.cleaned_data, prefix="%d_%d"%(layer_index, channel_index))
                 for channel_index, channel in enumerate(channel_form_lists[i])])

    # Second step: Add layers
    to_be_added_layers = utils.int_or_zero(change_params.get("structural-change-add-layers"))
    if to_be_added_layers < 0:
        to_be_added_layers = 0
    structure_changed = structure_changed or to_be_added_layers > 0
    for i in range(to_be_added_layers):
        layer_index = len(layer_forms) + len(new_layers)
        new_layers.append(LayerForm(initial={"number": biggest_layer_number+1}, prefix=str(layer_index)))
        biggest_layer_number += 1
        new_channel_lists.append([])
    # Third step: Add My Layer
    my_layer = change_params.get("structural-change-my_layer_to_be_added")
    if my_layer:
        structure_changed = True
        deposition_id, layer_number = my_layer.split("-")
        deposition_id, layer_number = int(deposition_id), int(layer_number)
        try:
            # FixMe: "find_actual_instance()" should be "sixchamberdeposition".
            # However, I don't know which exceptions are possible then.
            deposition = models.Deposition.objects.get(pk=deposition_id).find_actual_instance()
        except models.Deposition.DoesNotExist:
            pass
        else:
            layer_query = deposition.layers.filter(number=layer_number)
            if layer_query.count() == 1:
                layer = layer_query[0]
                layer_data = layer_query.values()[0]
                layer_data["number"] = biggest_layer_number + 1
                biggest_layer_number += 1
                layer_index = len(layer_forms) + len(new_layers)
                new_layers.append(LayerForm(initial=layer_data, prefix=str(layer_index)))
                new_channels = []
                for channel_index, channel_data in enumerate(layer.channels.values()):
                    new_channels.append(ChannelForm(initial=channel_data, prefix="%d_%d"%(layer_index, channel_index)))
                new_channel_lists.append(new_channels)

    # Forth and fifth steps: Add and delete channels
    for layer_index, channels in enumerate(channel_form_lists):
        # Add channels
        to_be_added_channels = utils.int_or_zero(change_params.get(
                "structural-change-add-channels-for-layerindex-%d" % layer_index))
        if to_be_added_channels < 0:
            to_be_added_channels = 0
        structure_changed = structure_changed or to_be_added_channels > 0
        number_of_channels = len(channels)
        for channel_index in range(number_of_channels, number_of_channels+to_be_added_channels):
            channels.append(ChannelForm(prefix="%d_%d"%(layer_index, channel_index)))
        # Delete channels
        to_be_deleted_channels = [channel_index for channel_index in range(number_of_channels)
                                  if "structural-change-delete-channelindex-%d-for-layerindex-%d" %
                                  (channel_index, layer_index) in change_params]
        structure_changed = structure_changed or bool(to_be_deleted_channels)
        for channel_index in reversed(to_be_deleted_channels):
            del channels[channel_index]

    # Sixth step: Delete layers
    to_be_deleted_layers = [layer_index for layer_index in range(len(layer_forms))
                            if "structural-change-delete-layerindex-%d" % layer_index in change_params]
    structure_changed = structure_changed or bool(to_be_deleted_layers)
    for layer_index in reversed(to_be_deleted_layers):
        del layer_forms[layer_index]

    # Apply changes
    layer_forms.extend(new_layers)
    channel_form_lists.extend(new_channel_lists)
    return structure_changed

def is_referentially_valid(deposition, deposition_form, layer_forms, channel_form_lists):
    u"""Test whether all forms are consistent with each other and with the
    database.  For example, no layer number must occur twice, and the
    deposition number must not exist within the database.

    :Parameters:
      - `deposition`: the currently edited deposition, or ``None`` if we create
        a new one
      - `deposition_form`: a bound deposition form
      - `layer_forms`: the list with all bound layer forms of the deposition
      - `channel_form_lists`: all bound channel forms of this deposition.  It
        is a list, and every item is again a list containing all the channels
        of the layer with the same index in ``layer forms``.

    :type deposition: `models.SixChamberDeposition` or ``NoneType``
    :type deposition_form: `DepositionForm`
    :type layer_forms: list of `LayerForm`
    :type channel_form_lists: list of lists of `ChannelForm`

    :Return:
      whether all forms are consistent with each other and the database

    :rtype: bool
    """
    referentially_valid = True
    if deposition_form.is_valid() and (
        not deposition or deposition.number != deposition_form.cleaned_data["number"]):
        if models.Deposition.objects.filter(number=deposition_form.cleaned_data["number"]).count():
            utils.append_error(deposition_form, _(u"This deposition number exists already."))
            referentially_valid = False
    if not layer_forms:
        utils.append_error(deposition_form, _(u"No layers given."))
        referentially_valid = False
    layer_numbers = set()
    for layer_form, channel_forms in zip(layer_forms, channel_form_lists):
        if layer_form.is_valid():
            if layer_form.cleaned_data["number"] in layer_numbers:
                utils.append_error(layer_form, _(u"Number is a duplicate."))
                referentially_valid = False
            else:
                layer_numbers.add(layer_form.cleaned_data["number"])
        channel_numbers = set()
        for channel_form in channel_forms:
            if channel_form.is_valid():
                if channel_form.cleaned_data["number"] in channel_numbers:
                    utils.append_error(channel_form, _(u"Number is a duplicate."))
                    referentially_valid = False
                else:
                    channel_numbers.add(channel_form.cleaned_data["number"])
    return referentially_valid
    
def save_to_database(deposition_form, layer_forms, channel_form_lists):
    u"""Save the forms to the database.  Only the deposition is just update if
    it already existed.  However, layers and channels are completely deleted
    and re-constructed from scratch.

    :Parameters:
      - `deposition_form`: a bound deposition form
      - `layer_forms`: the list with all bound layer forms of the deposition
      - `channel_form_lists`: all bound channel forms of this deposition.  It
        is a list, and every item is again a list containing all the channels
        of the layer with the same index in ``layer forms``.

    :type deposition_form: `DepositionForm`
    :type layer_forms: list of `LayerForm`
    :type channel_form_lists: list of lists of `ChannelForm`

    :Return:
      The daved deposition object

    :rtype: `models.SixChamberDeposition`
    """
    deposition = deposition_form.save()
    deposition.layers.all().delete()  # deletes channels, too
    for layer_form, channel_forms in zip(layer_forms, channel_form_lists):
        layer = layer_form.save(commit=False)
        layer.deposition = deposition
        layer.save()
        for channel_form in channel_forms:
            channel = channel_form.save(commit=False)
            channel.layer = layer
            channel.save()
    return deposition

def remove_samples_from_my_samples(samples, user_details):
    u"""Remove the given samples from the user's MySamples list

    :Parameters:
      - `samples`: the samples to be removed.  FixMe: How does it react if a
        sample hasn't been in ``my_samples``?
      - `user_details`: details of the user whose MySamples list is affected

    :type samples: list of `models.Sample`
    :type user_details: `models.UserDetails`
    """
    # FixMe: Should be moved to utils.py
    for sample in samples:
        user_details.my_samples.remove(sample)

def forms_from_post_data(post_data):
    u"""Interpret the POST data and create bound forms for layers and channels
    from it.  The top-level channel list has the same number of elements as the
    layer list because they correspond to each other.

    :Parameters:
      - `post_data`: the result from ``request.POST``

    :type post_data: ``QueryDict``

    :Return:
      list of layer forms, list of lists of channel forms

    :rtype: list of `LayerForm`, list of lists of `ChannelForm`
    """
    post_data, number_of_layers, list_of_number_of_channels = utils.normalize_prefixes(post_data)
    layer_forms = [LayerForm(post_data, prefix=str(layer_index)) for layer_index in range(number_of_layers)]
    channel_form_lists = []
    for layer_index in range(number_of_layers):
        channel_form_lists.append(
            [ChannelForm(post_data, prefix="%d_%d"%(layer_index, channel_index))
             for channel_index in range(list_of_number_of_channels[layer_index])])
    return layer_forms, channel_form_lists

def forms_from_database(deposition):
    u"""Take a deposition instance and construct forms from it for its layers
    and their channels.  The top-level channel list has the same number of
    elements as the layer list because they correspond to each other.

    :Parameters:
      - `deposition`: the deposition to be converted to forms.

    :type deposition: `models.Deposition`

    :Return:
      list of layer forms, list of lists of channel forms

    :rtype: list of `LayerForm`, list of lists of `ChannelForm`
    """
    layers = deposition.layers.all()
    layer_forms = [LayerForm(prefix=str(layer_index), instance=layer) for layer_index, layer in enumerate(layers)]
    channel_form_lists = []
    for layer_index, layer in enumerate(layers):
        channel_form_lists.append(
            [ChannelForm(prefix="%d_%d"%(layer_index, channel_index), instance=channel)
             for channel_index, channel in enumerate(layer.channels.all())])
    return layer_forms, channel_form_lists

query_string_pattern = re.compile(r"^copy_from=(?P<copy_from>.+)$")

@login_required
@check_permission("change_sixchamberdeposition")
def edit(request, deposition_number):
    u"""Central view for editing, creating, and duplicating 6-chamber
    depositions.  If `deposition_number` is ``None``, a new depositon is
    created (possibly by duplicating another one).

    :Parameters:
      - `request`: the HTTP request object
      - `deposition_number`: the number (=name) or the deposition

    :type request: ``QueryDict``
    :type deposition_number: unicode or ``NoneType``

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    deposition = get_object_or_404(SixChamberDeposition, number=deposition_number) if deposition_number else None
    user_details = request.user.get_profile()
    if request.method == "POST":
        deposition_form = DepositionForm(user_details, request.POST, instance=deposition)
        layer_forms, channel_form_lists = forms_from_post_data(request.POST)
        remove_from_my_samples_form = RemoveFromMySamples(request.POST)
        all_valid = is_all_valid(deposition_form, layer_forms, channel_form_lists, remove_from_my_samples_form)
        structure_changed = change_structure(layer_forms, channel_form_lists, request.POST)
        referentially_valid = is_referentially_valid(deposition, deposition_form, layer_forms, channel_form_lists)
        if all_valid and referentially_valid and not structure_changed:
            deposition = save_to_database(deposition_form, layer_forms, channel_form_lists)
            if remove_from_my_samples_form.cleaned_data["remove_deposited_from_my_samples"]:
                remove_samples_from_my_samples(deposition.samples.all(), user_details)
            if deposition_number:
                request.session["success_report"] = \
                    _(u"Deposition %s was successfully changed in the database.") % deposition.number
                return utils.HttpResponseSeeOther(django.core.urlresolvers.reverse("samples.views.main.main_menu"))
            else:
                if utils.is_remote_client(request):
                    return utils.respond_to_remote_client(deposition.number)
                else:
                    request.session["success_report"] = \
                        _(u"Deposition %s was successfully added to the database.") % deposition.number
                    return utils.HttpResponseSeeOther(django.core.urlresolvers.reverse(
                            "samples.views.split_after_deposition.split_and_rename_after_deposition",
                            kwargs={"deposition_number": deposition.number}))
    else:
        deposition_form = None
        # FixMe: Must make use of utils.parse_query_string
        match = query_string_pattern.match(request.META["QUERY_STRING"] or "")
        if not deposition and match:
            # Duplication of a deposition
            copy_from_query = models.SixChamberDeposition.objects.filter(number=match.group("copy_from"))
            if copy_from_query.count() == 1:
                deposition_data = copy_from_query.values()[0]
                del deposition_data["timestamp"]
                deposition_data["number"] = utils.get_next_deposition_number("B")
                deposition_form = DepositionForm(user_details, initial=deposition_data)
                layer_forms, channel_form_lists = forms_from_database(copy_from_query.all()[0])
        if not deposition_form:
            if deposition:
                # Normal edit of existing deposition
                deposition_form = DepositionForm(user_details, instance=deposition)
                layer_forms, channel_form_lists = forms_from_database(deposition)
            else:
                # New deposition, or duplication has failed
                deposition_form = DepositionForm(user_details, initial={"number": utils.get_next_deposition_number("B")})
                layer_forms, channel_form_lists = [], []
        remove_from_my_samples_form = RemoveFromMySamples(initial={"remove_deposited_from_my_samples": not deposition})
    add_my_layer_form = AddMyLayerForm(user_details=user_details, prefix="structural-change")
    title = _(u"6-chamber deposition “%s”") % deposition_number if deposition_number else _(u"New 6-chamber deposition")
    return render_to_response("edit_six_chamber_deposition.html",
                              {"title": title, "deposition": deposition_form,
                               "layers_and_channels": zip(layer_forms, channel_form_lists),
                               "add_my_layer": add_my_layer_form,
                               "remove_from_my_samples": remove_from_my_samples_form},
                              context_instance=RequestContext(request))

@login_required
def show(request, deposition_number):
    u"""Show an existing 6-chamber_deposision.  You must be a 6-chamber
    operator *or* be able to view one of the samples affected by this
    deposition in order to be allowed to view it.
    
    :Parameters:
      - `request`: the current HTTP Request object
      - `deposition_number`: the number (=name) or the deposition

    :type request: ``HttpRequest``
    :type deposition_number: unicode

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    deposition = get_object_or_404(SixChamberDeposition, number=deposition_number)
    samples = deposition.samples
    if all(not utils.has_permission_for_sample_or_series(request.user, sample) for sample in samples.all()) \
            and not request.user.has_perm("change_sixchamberdeposition"):
        return utils.HttpResponseSeeOther("permission_error")
    template_context = {"title": _(u"6-chamber deposition “%s”") % deposition.number, "samples": samples.all()}
    template_context.update(utils.ProcessContext(request.user).digest_process(deposition))
    return render_to_response("show_process.html", template_context, context_instance=RequestContext(request))
