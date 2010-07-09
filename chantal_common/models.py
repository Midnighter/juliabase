#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright © 2009 Torsten Bronger <bronger@physik.rwth-aachen.de>
#
# This file is part of Django-RefDB.
#
#     Django-RefDB is free software: you can redistribute it and/or
#     modify it under the terms of the GNU Affero General Public
#     License as published by the Free Software Foundation, either
#     version 3 of the License, or (at your option) any later
#     version.
#
#     Django-RefDB is distributed in the hope that it will be
#     useful, but WITHOUT ANY WARRANTY; without even the implied
#     warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
#     PURPOSE.  See the GNU Affero General Public License for more
#     details.
#
#     You should have received a copy of the GNU Affero General
#     Public License along with Django-RefDB.  If not, see
#     <http://www.gnu.org/licenses/>.


u"""Models in the relational database for Chantal-Common.
"""

import django.contrib.auth.models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.db import models
from django.utils.translation import ugettext_lazy as _


languages = (
    ("en", u"English"),
    ("de", u"Deutsch"),
    )
u"""Contains all possible choices for `UserDetails.language`.
"""

class UserDetails(models.Model):
    u"""Model for further details about a user, beyond
    ``django.contrib.auth.models.User``.  Here, you have all data about a
    registered user that is not stored by Django's user model itself.
    """
    user = models.OneToOneField(django.contrib.auth.models.User, primary_key=True, verbose_name=_(u"user"),
                                related_name="chantal_user_details")
    language = models.CharField(_(u"language"), max_length=10, choices=languages, default="de")

    class Meta:
        verbose_name = _(u"user details")
        verbose_name_plural = _(u"user details")

    def __init__(self, *args, **kwargs):
        super(UserDetails, self).__init__(*args, **kwargs)
        self._old = {"language": self.language}

    def __unicode__(self):
        return unicode(self.user)


class Topic(models.Model):
    u"""Model for topics of the institution (institute/company).  Every sample
    belongs to at most one topic.  Every user can be in an arbitrary number of
    topics.  The most important purpose of topics is to define permissions.
    Roughly speaking, a user can view samples of their topics.

    The attribute ``restricted`` means that senior users (i.e. users with the
    permission ``"view_all_samples"``) cannot view samples of restricted topics
    (in order to make non-disclosure agreements with external partners
    possible).
    """
    name = models.CharField(_("name"), max_length=80, unique=True)
    members = models.ManyToManyField(django.contrib.auth.models.User, blank=True, verbose_name=_(u"members"),
                                     related_name="topics")
    restricted = models.BooleanField(_(u"restricted"), default=False)

    class Meta:
        verbose_name = _(u"topic")
        verbose_name_plural = _(u"topics")
        _ = lambda x: x
        permissions = (("can_edit_all_topics", _("Can edit all topics, and can add new topics")),
                       ("can_edit_their_topics", _("Can edit topics that he/she is a member of")))

    def __unicode__(self):
        return unicode(self.name)


class PolymorphicModel(models.Model):
    u"""Abstract model class, which provides the attribute ``actual_instance``.
    This solves the problem that Django's ORM does not implement automatic
    resolution of polymorphy.  For example, if you get a list of Toppings,
    they're just Toppings.  However sometimes, you must have the actual object,
    i.e. CheeseTopping, SalamiTopping etc.  Then, ``topping.actual_instance``
    will give just that.

    Simply derive the top-level model class from this one, and then you can
    easily resolve polymorphy in it and its derived classes.
    """
    content_type = models.ForeignKey(ContentType, null=True, blank=True)
    actual_object_id = models.PositiveIntegerField(null=True, blank=True)
    actual_instance = generic.GenericForeignKey("content_type", "actual_object_id")

    def save(self, *args, **kwargs):
        u"""Saves the instance and assures that `actual_instance` is set.
        """
        super(PolymorphicModel, self).save(*args, **kwargs)
        if not self.actual_object_id:
            self.actual_instance = self
            super(PolymorphicModel, self).save()

    class Meta:
        abstract = True
