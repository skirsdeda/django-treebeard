function moveNodeFormOnRefNodeIdChanged(el, posElementId, posChoices) {
    // get selected Option and it's data attributes
    var option;
    for (var i=0; i<el.options.length; i++) {
        if (el.options[i].selected) {
            option=el.options[i];
            break;
        }
    }
    var isRoot = el.value === '0';
    var nodeSorted = option.dataset.sorted === '1';
    var nodeParentSorted = option.dataset.parentsorted === '1';
    
    // build new option list for node selection
    var newOptions;
    if (nodeSorted) {
        newOptions = posChoices.sorted_child;
    }
    else {
        newOptions = isRoot ? posChoices.unsorted_root_child : posChoices.unsorted_child;
    }
    
    if (!isRoot) {
        // node selected (not --root--)
        var sibOpts = nodeParentSorted ? posChoices.sorted_sib : posChoices.unsorted_sib;
        newOptions = newOptions.concat(sibOpts);
    }

    // update DOM with new option list
    var posSelect = document.getElementById(posElementId);
    posSelect.options.length = 0;
    for (var i=0; i<newOptions.length; i++) {
        posSelect.options[i] = new Option(newOptions[i][1], newOptions[i][0]);
    }
}
