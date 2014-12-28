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


"""
FixMe: Layout files should be taken from cache if appropriate.
"""

from __future__ import unicode_literals, absolute_import, division

import os.path, subprocess
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
import jb_common.utils.base
import samples.utils.views as utils
from institute import models
from institute import layouts


@login_required
def show_layout(request, process_id, sample_id):
    sample = get_object_or_404(models.Sample, pk=utils.convert_id_to_int(sample_id))
    process = get_object_or_404(models.Process, pk=utils.convert_id_to_int(process_id)).actual_instance

    pdf_filename = "/tmp/layouts_{0}_{1}.pdf".format(process.id, sample.id)
    jb_common.utils.base.mkdirs(pdf_filename)
    layout = layouts.get_layout(sample, process)
    if not layout:
        raise Http404("error")
    layout.generate_pdf(pdf_filename)

    png_filename = os.path.join(settings.CACHE_ROOT, "layouts", "{0}-{1}.png".format(process.id, sample.id))
    jb_common.utils.base.mkdirs(png_filename)
    resolution = settings.THUMBNAIL_WIDTH / (layout.width / 72)
    subprocess.check_call(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pngalpha", "-r{0}".format(resolution), "-dEPSCrop",
                             "-sOutputFile=" + png_filename, pdf_filename])
    return jb_common.utils.base.static_file_response(png_filename)
