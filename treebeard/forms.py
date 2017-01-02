"""Forms for treebeard."""
import json

from django import forms
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.query import QuerySet
from django.forms.models import modelform_factory as django_modelform_factory
from django.forms.models import BaseModelForm, ErrorList, model_to_dict
from django.utils.encoding import force_text
from django.utils.functional import Promise
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from treebeard.al_tree import AL_Node
from treebeard.mp_tree import MP_Node
from treebeard.ns_tree import NS_Node


__all__ = (
    'NodeSelect', 'MoveNodeForm', 'movenodeform_factory',
    '_get_exclude_for_model',
)


class LazyEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, Promise):
            return force_text(obj)
        return super(LazyEncoder, self).default(obj)


class NodeSelect(forms.Select):
    """
    Enhanced select widget which adds data attributes to options
    and uses onchanged event handler to update position field choices.
    """
    class Media:
        js = ('treebeard/movenodeform.js',)

    def __init__(self, position_field_id, attrs=None, choices=()):
        super(NodeSelect, self).__init__(attrs, choices)
        self.position_field_id = position_field_id

    def render(self, name, value, attrs=None):
        if attrs is None:
            attrs = {}
        # inject onchaged event handler
        choices_json = json.dumps(MoveNodeForm.position_choices,
                                  cls=LazyEncoder)
        attrs.update({
            'onchange':
                "moveNodeFormOnRefNodeIdChanged(this, '{}', {})".format(
                    self.position_field_id, choices_json),
        })

        return super(NodeSelect, self).render(name, value, attrs)

    def render_option(self, selected_choices, option_value, option_label):
        # in this case option_label can be a dict containing not only label
        # but also data-* attributes to be added to option
        if option_value is None:
            option_value = ''
        option_value = force_text(option_value)
        if option_value in selected_choices:
            add_html = ' selected="selected"'
            if not self.allow_multiple_selected:
                # Only allow for a single selection.
                selected_choices.remove(option_value)
        else:
            add_html = ''
        if isinstance(option_label, dict):
            option_data = option_label
            option_label = option_data.pop('label')
            for k, v in option_data.items():
                add_html += ' data-{}="{}"'.format(k, v)
        add_html = mark_safe(add_html)
        return format_html('<option value="{}"{}>{}</option>',
                           option_value,
                           add_html,
                           force_text(option_label))


class MoveNodeForm(forms.ModelForm):
    """
    Form to handle moving a node in a tree.

    Handles sorted/unsorted trees.

    It adds two fields to the form:

    - Relative to: The target node where the current node will
                   be moved to.
    - Position: The position relative to the target node that
                will be used to move the node. These can be:

                - For sorted trees: ``Child of`` and ``Sibling of``
                - For unsorted trees: ``First child of``, ``Before`` and
                  ``After``

    .. warning::

        Subclassing :py:class:`MoveNodeForm` directly is
        discouraged, since special care is needed to handle
        excluded fields, and these change depending on the
        tree type.

        It is recommended that the :py:func:`movenodeform_factory`
        function is used instead.

    """

    pos_sorted_child = (
        ('sorted-child', _('Child of')),
    )

    pos_sorted_sib = (
        ('sorted-sibling', _('Sibling of')),
    )

    position_choices_sorted = pos_sorted_child + pos_sorted_sib


    pos_unsorted_child = (
        ('first-child', _('First child of')),
    )

    # All unsorted root children are added last
    pos_unsorted_root_child = (
        ('root-child', _('Last child of')),
    )

    pos_unsorted_sib = (
        ('left', _('Before')),
        ('right', _('After')),
    )

    position_choices_unsorted = pos_unsorted_child + pos_unsorted_sib

    position_choices = {
        'sorted_child': pos_sorted_child,
        'sorted_sib': pos_sorted_sib,
        'unsorted_child': pos_unsorted_child,
        'unsorted_root_child': pos_unsorted_root_child,
        'unsorted_sib': pos_unsorted_sib,
    }

    _ref_node_id = forms.TypedChoiceField(
        required=False,
        coerce=int,
        widget=NodeSelect('id__position'),
        label=_("Relative to"))

    _position = forms.ChoiceField(required=True,
                                  label=_("Position"))

    def _get_position_ref_node(self, instance):
        if instance.is_parent_sorted():
            position = 'sorted-child'
            node_parent = instance.get_parent()
            if node_parent:
                ref_node_id = node_parent.pk
            else:
                ref_node_id = 0
        else:
            prev_sibling = instance.get_prev_sibling()
            if prev_sibling:
                position = 'right'
                ref_node_id = prev_sibling.pk
            else:
                if instance.is_root():
                    position = 'root-child'
                    ref_node_id = 0
                else:
                    position = 'first-child'
                    ref_node_id = instance.get_parent().pk
        return {'_ref_node_id': ref_node_id,
                '_position': position}

    def __init__(self, data=None, files=None, auto_id='id_%s', prefix=None,
                 initial=None, error_class=ErrorList, label_suffix=':',
                 empty_permitted=False, instance=None, **kwargs):
        opts = self._meta
        if opts.model is None:
            raise ValueError('ModelForm has no model class specified')

        # update the '_ref_node_id' choices
        choices = self.mk_dropdown_tree(opts.model, for_node=instance)
        self.declared_fields['_ref_node_id'].choices = choices

        # put initial data for these fields into a map, update the map with
        # initial data, and pass this new map to the parent constructor as
        # initial data
        if instance is None:
            initial_ = {}
        else:
            initial_ = self._get_position_ref_node(instance)

        if initial is not None:
            initial_.update(initial)

        super(MoveNodeForm, self).__init__(
            data, files, auto_id, prefix, initial_, error_class, label_suffix,
            empty_permitted, instance, **kwargs)

        # update the '_position' field choices
        self.is_root_sorted = getattr(opts.model, 'node_order_by', False)
        self._adapt_position_choices()

    def _adapt_position_choices(self):
        ref_node_id = self.data.get('_ref_node_id')
        if ref_node_id is not None:
            ref_node_id = int(ref_node_id)
        else:
            ref_node_id = self.initial.get('_ref_node_id', 0)
        ref_node_choices = self.fields['_ref_node_id'].choices
        ref_node_choice = None
        for v, choice in ref_node_choices:
            if v == ref_node_id:
                ref_node_choice = choice
                break
        if ref_node_choice is None:
            return

        sorted = ref_node_choice.get('sorted', False)
        parent_sorted = ref_node_choice.get('parentsorted', False)
        if sorted:
            new_choices = self.pos_sorted_child
        else:
            if ref_node_id == 0:
                new_choices = self.pos_unsorted_root_child
            else:
                new_choices = self.pos_unsorted_child
        if ref_node_id != 0:
            if parent_sorted:
                new_choices += self.pos_sorted_sib
            else:
                new_choices += self.pos_unsorted_sib
        self.fields['_position'].choices = new_choices

    def _clean_cleaned_data(self):
        """ delete auxilary fields not belonging to node model """
        reference_node_id = 0

        if '_ref_node_id' in self.cleaned_data:
            reference_node_id = self.cleaned_data['_ref_node_id']
            del self.cleaned_data['_ref_node_id']

        position_type = self.cleaned_data['_position']
        del self.cleaned_data['_position']

        return position_type, reference_node_id

    def full_clean(self):
        self._adapt_position_choices()
        return super(MoveNodeForm, self).full_clean()

    def save(self, commit=True):
        position_type, reference_node_id = self._clean_cleaned_data()

        if self.instance.pk is None:
            cl_data = {}
            for field in self.cleaned_data:
                if not isinstance(self.cleaned_data[field], (list, QuerySet)):
                    cl_data[field] = self.cleaned_data[field]
            if reference_node_id:
                reference_node = self._meta.model.objects.get(
                    pk=reference_node_id)
                self.instance = reference_node.add_child(**cl_data)
                self.instance.move(reference_node, pos=position_type)
            else:
                self.instance = self._meta.model.add_root(**cl_data)
        else:
            self.instance.save()
            if reference_node_id:
                reference_node = self._meta.model.objects.get(
                    pk=reference_node_id)
                self.instance.move(reference_node, pos=position_type)
            else:
                if self.is_root_sorted:
                    pos = 'sorted-sibling'
                else:
                    pos = 'first-sibling'
                self.instance.move(self._meta.model.get_first_root_node(), pos)
        # Reload the instance
        self.instance = self._meta.model.objects.get(pk=self.instance.pk)
        super(MoveNodeForm, self).save(commit=commit)
        return self.instance

    @staticmethod
    def is_loop_safe(for_node, possible_parent):
        if for_node is not None:
            return not (
                possible_parent == for_node
                ) or (possible_parent.is_descendant_of(for_node))
        return True

    @staticmethod
    def mk_indent(level):
        return '&nbsp;&nbsp;&nbsp;&nbsp;' * (level - 1)

    @classmethod
    def add_subtree(cls, for_node, node, options):
        """ Recursively build options tree. """
        if cls.is_loop_safe(for_node, node):
            label = mark_safe(cls.mk_indent(node.get_depth()) + escape(node))
            options.append(
                (node.pk,
                 {'label': label,
                  'sorted': int(node.is_sorted()),
                  'parentsorted': int(node.is_parent_sorted()),}))
            for subnode in node.get_children():
                cls.add_subtree(for_node, subnode, options)

    @classmethod
    def mk_dropdown_tree(cls, model, for_node=None):
        """ Creates a tree-like list of choices """

        options = [(0, {'sorted': int(bool(model.node_order_by)),
                        'label': _('-- root --')})]
        for node in model.get_root_nodes():
            cls.add_subtree(for_node, node, options)
        return options


def movenodeform_factory(model, form=MoveNodeForm, fields=None, exclude=None,
                         formfield_callback=None,  widgets=None):
    """Dynamically build a MoveNodeForm subclass with the proper Meta.

    :param Node model:

        The subclass of :py:class:`Node` that will be handled
        by the form.

    :param form:

        The form class that will be used as a base. By
        default, :py:class:`MoveNodeForm` will be used.

    :return: A :py:class:`MoveNodeForm` subclass
    """
    _exclude = _get_exclude_for_model(model, exclude)
    return django_modelform_factory(
        model, form, fields, _exclude, formfield_callback, widgets)


def _get_exclude_for_model(model, exclude):
    if exclude:
        _exclude = tuple(exclude)
    else:
        _exclude = ()
    if issubclass(model, AL_Node):
        _exclude += ('sib_order', 'parent')
    elif issubclass(model, MP_Node):
        _exclude += ('depth', 'numchild', 'path')
    elif issubclass(model, NS_Node):
        _exclude += ('depth', 'lft', 'rgt', 'tree_id')
    return _exclude
