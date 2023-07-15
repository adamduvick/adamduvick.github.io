const FAST_ANIMATION = 100; // ms
const SLOW_ANIMATION = 500; // ms
const noteButtons = [];

function toggleNote(element) {
    let className = element.attr("class").match(/note\d{2}/g)[0];
    console.log(className + " toggled");
    var $button = $(".note-panel circle." + className);
    $button.toggleClass("toggled");
    if ($button.hasClass("toggled")) {
        highlightNote(element);
    } else {
        unhighlightNote(element);
    }
    updateIncidentals();
}

function highlightNote(element) {
    let className = element.attr("class").match(/note\d{2}/g)[0];
    console.log(className + " highlighted");
    if ($(".note-panel circle." + className).hasClass("toggled")) {
        $(".note-panel circle." + className).css("stroke", "black").animate({
            r: "4%"
        }, FAST_ANIMATION);
        $(".note-panel text." + className).fadeTo(FAST_ANIMATION, 0.85)
        $('.fretboard circle.' + className).css("stroke", "black").fadeTo(FAST_ANIMATION, 1);
    } else {
        $(".note-panel circle." + className).css("stroke", "white").animate({
            r: "4%"
        }, FAST_ANIMATION);
        $(".note-panel text." + className).fadeTo(FAST_ANIMATION, 0.85);
        $('.fretboard circle.' + className).css("stroke", "white").fadeTo(FAST_ANIMATION, 0.5);
    }
}

function unhighlightNote(element) {
    let className = element.attr("class").match(/note\d{2}/g)[0];
    console.log(className + " unhighlighted")
    if ($(".note-panel circle." + className).hasClass("toggled")) {
        $(".note-panel circle." + className).css("stroke", "white");
        $('.fretboard circle.' + className).css("stroke", "white");
    } else {
        $(".note-panel text." + className).fadeOut(FAST_ANIMATION)
        $(".note-panel circle." + className).css("stroke", "white").animate({
            r: "2%"
        }, FAST_ANIMATION);
        $('.fretboard circle.' + className).fadeTo(FAST_ANIMATION, 0.01);
    }
}

function updateIncidentals() {
    if ($(".note-panel circle.note01").hasClass("toggled") & $(".note-panel circle.note03").hasClass("toggled")) {
        $(".note-panel text.note02").html('G<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else if ($(".note-panel circle.note01").hasClass("toggled")) {
        $(".note-panel text.note02").html('A<tspan dy="-6%" dx="0%" font-size="10">&#x266D;</tspan>');
    } else if ($(".note-panel circle.note03").hasClass("toggled")) {
        $(".note-panel text.note02").html('G<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else {
        $(".note-panel text.note02").html('G<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    }
    if ($(".note-panel circle.note03").hasClass("toggled") & $(".note-panel circle.note05").hasClass("toggled")) {
        $(".note-panel text.note04").html('A<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else if ($(".note-panel circle.note03").hasClass("toggled")) {
        $(".note-panel text.note04").html('B<tspan dy="-6%" dx="0%" font-size="10">&#x266D;</tspan>');
    } else if ($(".note-panel circle.note05").hasClass("toggled")) {
        $(".note-panel text.note04").html('A<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else {
        $(".note-panel text.note04").html('A<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    }
    if ($(".note-panel circle.note06").hasClass("toggled") & $(".note-panel circle.note08").hasClass("toggled")) {
        $(".note-panel text.note07").html('C<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else if ($(".note-panel circle.note06").hasClass("toggled")) {
        $(".note-panel text.note07").html('D<tspan dy="-6%" dx="0%" font-size="10">&#x266D;</tspan>');
    } else if ($(".note-panel circle.note08").hasClass("toggled")) {
        $(".note-panel text.note07").html('C<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else {
        $(".note-panel text.note07").html('C<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    }
    if ($(".note-panel circle.note08").hasClass("toggled") & $(".note-panel circle.note10").hasClass("toggled")) {
        $(".note-panel text.note09").html('D<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else if ($(".note-panel circle.note08").hasClass("toggled")) {
        $(".note-panel text.note09").html('E<tspan dy="-6%" dx="0%" font-size="10">&#x266D;</tspan>');
    } else if ($(".note-panel circle.note10").hasClass("toggled")) {
        $(".note-panel text.note09").html('D<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else {
        $(".note-panel text.note09").html('D<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    }
    if ($(".note-panel circle.note11").hasClass("toggled") & $(".note-panel circle.note01").hasClass("toggled")) {
        $(".note-panel text.note12").html('F<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else if ($(".note-panel circle.note11").hasClass("toggled")) {
        $(".note-panel text.note12").html('G<tspan dy="-6%" dx="0%" font-size="10">&#x266D;</tspan>');
    } else if ($(".note-panel circle.note01").hasClass("toggled")) {
        $(".note-panel text.note12").html('F<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    } else {
        $(".note-panel text.note12").html('F<tspan dy="-6%" dx="0%" font-size="10">&#x266F;</tspan>');
    }
}

function shiftToggles(shiftRight) {
    let offset = shiftRight ? 1 : -1;
    let toToggle = [];
    for (var i = 0; i < noteButtons.length; i++) {
        let className = noteButtons[i];
        let shiftedClassName = noteButtons[(i + offset + 12) % 12];
        if ($(".note-panel circle." + className).hasClass("toggled")) {
            toToggle.push(shiftedClassName);
        }
    }
    for (var i = 0; i < noteButtons.length; i++) {
        let className = noteButtons[i];
        if (toToggle.includes(className)) {
            if (!$(".note-panel circle." + className).hasClass("toggled")) {
                toggleNote($(".note-panel circle." + className));
                unhighlightNote($(".note-panel circle." + className));
            }
        } else {
            if ($(".note-panel circle." + className).hasClass("toggled")) {
                toggleNote($(".note-panel circle." + className));
            }
        }
    }
}

$(document).ready(function () {
    // assign callback methods to note panel buttons
    for (var i = 1; i <= 12; i++) {
        let buttonClassName = "note" + ("0" + i).slice(-2);
        $("circle." + buttonClassName).click(function () {
            toggleNote($(this));
        }).hover(function () {
            highlightNote($(this));
        }, function () {
            unhighlightNote($(this));
        });
        noteButtons.push(buttonClassName);
    }
    $("#shift-left").click(function () {
        $(this).css("opacity", ".7").fadeTo(SLOW_ANIMATION, 1);
        shiftToggles(shiftRight = false);
    }).hover(function () {
        $(this).animate({
            strokeWidth: 20
        }, FAST_ANIMATION);
    }, function () {
        $(this).animate({
            strokeWidth: 3
        }, FAST_ANIMATION)
    })
    $("#shift-right").click(function () {
        $(this).css("opacity", ".7").fadeTo(SLOW_ANIMATION, 1);
        shiftToggles(shiftRight = true);
    }).hover(function () {
        $(this).animate({
            strokeWidth: 20
        }, FAST_ANIMATION);
    }, function () {
        $(this).animate({
            strokeWidth: 3
        }, FAST_ANIMATION);
    })

    $('circle.tuner').click(function () {
        element = $(this);
        let className = element.attr("class").match(/string\d{2}/g)[0];
        let noteIndex = parseInt(element.attr('class').match(/note(\d{2})/)[1]);
        console.log(className, noteIndex);
        $("circle." + className).each(function (index) {
            console.log(index);
            let newNote = (noteIndex + index) % 12 + 1;
            $(this).removeClass($(this).attr('class').match(/note(\d{2})/)[0]);
            $(this).addClass(`note${("0" + newNote).slice(-2)}`);
        })
    })

    // animate the board to help user understand how it works
    $('div.fretboard').animate({
        scrollLeft: ($('div.fretboard svg').width() / 100) * 8
    }, SLOW_ANIMATION);
    $('.fretboard circle.scale-note').fadeTo(SLOW_ANIMATION, 0.01);
    $('.note-panel text').fadeOut(SLOW_ANIMATION);
    $('.note-panel circle').animate({
        r: "2%"
    }, SLOW_ANIMATION);
});
