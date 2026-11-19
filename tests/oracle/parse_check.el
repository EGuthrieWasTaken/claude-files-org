;;; parse_check.el --- check that org-element can parse a file  -*- lexical-binding: t; -*-
(require 'org)
(require 'org-element)
(let ((file (car command-line-args-left)))
  (with-temp-buffer
    (insert-file-contents file)
    (org-mode)
    (org-element-parse-buffer)
    (princ (format "OK %s\n" (file-name-nondirectory file)))))
