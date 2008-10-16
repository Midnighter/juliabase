#!/usr/bin/env python
# -*- coding: utf-8 -*-

u"""Views for showing and editing user data, i.e. real names, contact
information, and preferences.
"""

import re
from django.template import RequestContext
from django.shortcuts import render_to_response, get_object_or_404
from django.contrib.auth.decorators import login_required
import django.contrib.auth.models
from django import forms
from django.forms.util import ValidationError
from django.utils.translation import ugettext as _, ugettext_lazy
from chantal.samples import models
from chantal.samples.views import utils

@login_required
def show_user(request, login_name):
    u"""View for showing basic information about a user, like the email
    address.  Maybe this could be fleshed out with phone number, picture,
    position, and field of interest.

    :Parameters:
      - `request`: the current HTTP Request object
      - `login_name`: the login name of the user to be shown

    :type request: ``HttpRequest``
    :type login_name: str

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    user = get_object_or_404(django.contrib.auth.models.User, username=login_name)
    userdetails = utils.get_profile(user)
    username = models.get_really_full_name(user)
    return render_to_response("show_user.html", {"title": username, "user": user, "userdetails": userdetails},
                              context_instance=RequestContext(request))

class UserDetailsForm(forms.ModelForm):
    u"""Model form for user preferences.  I exhibit only two field here, namely
    the auto-addition groups and the switch whether a user wants to get only
    important news or all.
    """
    _ = ugettext_lazy
    def __init__(self, user, *args, **keyw):
        super(UserDetailsForm, self).__init__(*args, **keyw)
        self.fields["auto_addition_groups"].queryset = user.groups
    class Meta:
        model = models.UserDetails
        fields = ("auto_addition_groups", "only_important_news")

initials_pattern = re.compile(ur"[A-Z]{2,4}[0-9]*$")
class InitialsForm(forms.Form):
    u"""Form for the user's initials.  Initials are optional, however, if you
    choose them, you cannot change (or delete) them anymore.
    """
    _ = ugettext_lazy
    initials = forms.CharField(label=_(u"Initials"), min_length=2, max_length=4, required=False)
    def __init__(self, user, *args, **keyw):
        super(InitialsForm, self).__init__(*args, **keyw)
        if user.initials:
            self.fields["initials"].widget.attrs["readonly"] = "readonly"
    def clean_initials(self):
        initials = self.cleaned_data["initials"]
        if not initials:
            return initials
        # Note that minimal and maximal length are already checked.
        if not initials_pattern.match(initials):
            raise ValidationError(_(u"The initials must start with two uppercase letters.  "
                                    u"They must contain uppercase letters and digits only.  Digits must be at the end."))
        if models.Initials.objects.filter(initials=initials).count():
            raise ValidationError(_(u"These initials are already used."))

@login_required
def edit_preferences(request, login_name):
    u"""View for editing preferences of a user.  Note that by giving the
    ``login_name`` explicitly, it is possible to edit the preferences of
    another user.  However, this is only allowed to staff.  The main reason for
    this explicitness is to be more “RESTful”.

    You can't switch the prefered language here because there are the flags
    anyway.

    Moreover, for good reason, you can't change your real name here.  This is
    taken automatically from the domain database through LDAP.  I want to give
    as few options as possible in order to avoid misbehaviour.

    :Parameters:
      - `request`: the current HTTP Request object
      - `login_name`: the login name of the user who's preferences should be
        edited.

    :type request: ``HttpRequest``
    :type login_name: unicode

    :Returns:
      the HTTP response object

    :rtype: ``HttpResponse``
    """
    user = get_object_or_404(django.contrib.auth.models.User, username=login_name)
    if not request.user.is_staff and request.user != user:
        return utils.HttpResponseSeeOther("permission_error")
    user_details = utils.get_profile(user)
    if request.method == "POST":
        user_details_form = UserDetailsForm(user, request.POST, instance=user_details)
        initials_form = InitialsForm(user, request.POST)
        if user_details_form.is_valid() and initials_form.is_valid():
            user_details_form.save()
            initials = initials_form.cleaned_data["initials"]
            if initials and models.Initials.objects.filter(user=user).count() == 0:
                models.Initials.objects.create(initials=initials, user=user)
            return utils.successful_response(request, _(u"The preferences were successfully updated."))
    else:
        user_details_form = UserDetailsForm(user, instance=user_details)
        initials_form = InitialsForm(user)
    return render_to_response("edit_preferences.html", {"title": login_name, "user_details": user_details_form,
                                                        "initials": initials_form},
                              context_instance=RequestContext(request))
    