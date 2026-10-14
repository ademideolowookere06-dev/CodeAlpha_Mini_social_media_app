document.addEventListener("DOMContentLoaded", function () {
    const postForms = document.querySelectorAll(
        '.create-post form, .comment-form'
    );

    postForms.forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const textArea = form.querySelector("textarea");
            const textInput = form.querySelector('input[name="content"]');

            const field = textArea || textInput;

            if (field && !field.value.trim()) {
                event.preventDefault();
                alert("Please enter some text before submitting.");
                field.focus();
            }
        });
    });
});
