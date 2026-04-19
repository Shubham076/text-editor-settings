# Linux / macOS Commands Cheat Sheet

A day-to-day reference for essential terminal commands.

---

## Table of Contents

- [cat](#cat)
- [head](#head)
- [tail](#tail)
- [grep](#grep)
- [zgrep](#zgrep)
- [find](#find)
- [ls](#ls)
- [sort](#sort)
- [sed](#sed)
- [awk](#awk)
- [df](#df)
- [du](#du)
- [pkill](#pkill)
- [Common Piped Commands](#common-piped-commands)

---

## cat

**C**oncatenate — display, create, and combine files.

### Display file contents

```bash
cat file.txt                     # print entire file
cat -n file.txt                  # print with line numbers
cat -b file.txt                  # number only non-blank lines
cat file1.txt file2.txt          # concatenate and print two files
```

### Write to a file

```bash
# Overwrite (creates if doesn't exist)
cat > file.txt
Type your content here.
Press Ctrl+D to save.

# Append to existing file
cat >> file.txt
This gets added at the end.
Ctrl+D to save.
```

### Combine files

```bash
cat file1.txt file2.txt > combined.txt      # merge into one file
cat header.txt body.txt footer.txt > page.txt
```

### Useful tricks

```bash
cat /dev/null > file.txt         # empty a file without deleting it
cat << EOF > config.txt          # heredoc — write multi-line content
host=localhost
port=8080
EOF
```

---

## head

Show the **first N lines** of a file or stream (default: 10).

```bash
head file.txt                    # first 10 lines
head -n 5 file.txt               # first 5 lines
head -20 file.txt                # first 20 lines (shorthand)
head -c 100 file.txt             # first 100 bytes
```

---

## tail

Show the **last N lines** of a file or stream (default: 10).

```bash
tail file.txt                    # last 10 lines
tail -n 5 file.txt               # last 5 lines
tail -20 file.txt                # last 20 lines (shorthand)
tail -f app.log                  # follow — stream new lines in real time
tail -f app.log | grep error     # follow and filter for errors
tail -n +5 file.txt              # print from line 5 onward
```

---

## grep

**G**lobal **R**egular **E**xpression **P**rint — search for patterns in text.

### Basic usage

```bash
grep "error" file.log                    # lines containing "error"
grep -i "error" file.log                 # case-insensitive
grep -r "TODO" ./src                     # recursive search in directory
grep -n "error" file.log                 # show line numbers
grep -c "error" file.log                 # count matching lines
grep -l "error" *.log                    # list filenames with matches only
```

### Invert and context

```bash
grep -v "debug" file.log                 # lines NOT containing "debug"
grep -A 3 "error" file.log              # show 3 lines After match
grep -B 2 "error" file.log              # show 2 lines Before match
grep -C 2 "error" file.log              # show 2 lines of Context (before + after)
```

### Regex

```bash
grep -E "error|warning" file.log         # extended regex (OR)
grep "^start" file.txt                   # lines starting with "start"
grep "end$" file.txt                     # lines ending with "end"
grep -w "port" file.txt                  # whole word match only
grep -P "\d{3}-\d{4}" file.txt          # Perl regex (Linux only)
```

### Flags reference

| Flag | Full meaning | Description |
|------|-------------|-------------|
| `-i` | **I**gnore case | Case-insensitive |
| `-r` | **R**ecursive | Search subdirectories |
| `-n` | Line **n**umber | Show line numbers |
| `-c` | **C**ount | Count matches |
| `-l` | **L**ist files | Show filenames only |
| `-v` | In**v**ert | Show non-matching lines |
| `-w` | **W**ord | Whole word match |
| `-E` | **E**xtended regex | Enables `|`, `+`, `?` without escaping |
| `-A N` | **A**fter | N lines after match |
| `-B N` | **B**efore | N lines before match |
| `-C N` | **C**ontext | N lines before + after |
| `-o` | **O**nly matching | Print only the matched part |

---

## zgrep

Same as `grep`, but works on **compressed files** (`.gz`) without decompressing them first.

```bash
zgrep "error" app.log.gz                 # search inside gzipped file
zgrep -i "timeout" /var/log/*.gz         # case-insensitive, multiple files
zgrep -c "404" access.log.gz             # count matches in compressed log
```

### Related compressed-file tools

| Command | Equivalent of | Works on |
|---------|--------------|----------|
| `zgrep` | `grep` | `.gz` files |
| `zcat` | `cat` | `.gz` files |
| `zless` | `less` | `.gz` files |
| `zdiff` | `diff` | `.gz` files |

---

## find

Search for files and directories in a directory tree.

### Basic usage

```bash
find /path -name "*.log"                 # find by name (case-sensitive)
find /path -iname "*.LOG"               # find by name (case-insensitive)
find . -type f                           # files only
find . -type d                           # directories only
```

### By size

```bash
find . -size +100M                       # files larger than 100MB
find . -size -1k                         # files smaller than 1KB
find . -empty                            # empty files and directories
```

### By time

```bash
find . -mtime -7                         # modified in last 7 days
find . -mtime +30                        # modified more than 30 days ago
find . -mmin -60                         # modified in last 60 minutes
find . -newer reference.txt              # modified after reference.txt
```

### By permissions and ownership

```bash
find . -perm 755                         # exact permission match
find . -user shubham                     # owned by user
```

### Execute actions on results

```bash
find . -name "*.tmp" -delete             # delete matching files
find . -name "*.sh" -exec chmod +x {} \; # make scripts executable
find . -name "*.log" -exec grep -l "error" {} \;  # grep in found files
```

### Combine conditions

```bash
find . -name "*.py" -and -size +10k      # AND
find . -name "*.log" -or -name "*.txt"   # OR
find . -not -name "*.tmp"                # NOT
find . -name "*.log" ! -path "*/vendor/*"  # exclude paths
```

### Flags reference

| Flag | Description |
|------|-------------|
| `-name` | Match filename (case-sensitive, supports `*`, `?`) |
| `-iname` | Match filename (case-insensitive) |
| `-type f` | Files only |
| `-type d` | Directories only |
| `-size` | Filter by size (`+`=larger, `-`=smaller, `c/k/M/G`) |
| `-mtime` | Modified time in days |
| `-mmin` | Modified time in minutes |
| `-maxdepth N` | Limit search depth |
| `-exec CMD {} \;` | Run command on each result |
| `-delete` | Delete matching files |
| `-empty` | Match empty files/dirs |

---

## ls

**L**i**s**t directory contents.

```bash
ls                                       # list files in current dir
ls -l                                    # long format (permissions, size, date)
ls -la                                   # long format + hidden files
ls -lh                                   # long format + human-readable sizes
ls -lt                                   # sort by modification time (newest first)
ls -ltr                                  # sort by time, reversed (oldest first)
ls -lS                                   # sort by size (largest first)
ls -lSh                                  # sort by size + human-readable (KB, MB, GB)
ls -lShr                                 # sort by size, smallest first (reversed)
ls -R                                    # recursive listing
ls -d */                                 # list only directories
ls -1                                    # one file per line
```

### Flags reference

| Flag | Full meaning | Description |
|------|-------------|-------------|
| `-l` | **L**ong | Detailed listing |
| `-a` | **A**ll | Include hidden files (dotfiles) |
| `-h` | **H**uman-readable | Sizes in KB/MB/GB |
| `-t` | **T**ime | Sort by modification time |
| `-S` | **S**ize | Sort by file size |
| `-r` | **R**everse | Reverse sort order |
| `-R` | **R**ecursive | List subdirectories |
| `-d` | **D**irectory | List directories themselves, not contents |
| `-1` | One per line | Single column output |

### Understanding `ls -l` output

```
-rwxr-xr-x  1  shubham  staff  4096  Apr 8 15:00  script.py
│├─┤├─┤├─┤  │  │        │      │     │             │
│ │   │  │  │  owner   group  size  date          filename
│ │   │  └─ others: r-x (read + execute)
│ │   └──── group:  r-x (read + execute)
│ └──────── owner:  rwx (read + write + execute)
└────────── type: - = file, d = directory, l = symlink
```

---

## sort

Sort lines of text.

```bash
sort file.txt                            # alphabetical (default)
sort -n file.txt                         # numeric
sort -r file.txt                         # reverse
sort -nr file.txt                        # numeric + reverse (descending)
sort -h file.txt                         # human-readable numbers (1K < 1M < 1G)
sort -u file.txt                         # unique (remove duplicates)
sort -k2,2 file.txt                      # sort by 2nd column only
sort -k2,2 -n -k3,3 -nr file.txt        # 2nd col ascending, 3rd col descending
sort -t',' -k2,2 file.csv               # comma delimiter, sort by 2nd field
```

### Flags reference

| Flag | Full meaning | Description |
|------|-------------|-------------|
| `-n` | **N**umeric | Sort as numbers |
| `-h` | **H**uman-numeric | Understands K, M, G, T suffixes |
| `-r` | **R**everse | Descending order |
| `-k` | **K**ey | Sort by specific column |
| `-t` | Field **t**erminator | Set column delimiter |
| `-u` | **U**nique | Remove duplicates |
| `-f` | **F**old case | Case-insensitive |
| `-o` | **O**utput | Write result to file |

### `-k` key syntax

```
-k2       →  sort from field 2 to END of line (greedy)
-k2,2     →  sort by field 2 ONLY (precise)
-k2,3     →  sort by fields 2 through 3
```

> Always use `-k2,2` (with end field) when combining multiple `-k` flags.

---

## sed

**S**tream **Ed**itor — find-and-replace, line editing.

### Substitution

```bash
sed 's/old/new/' file.txt                # replace first match per line
sed 's/old/new/g' file.txt               # replace all matches per line
sed 's/old/new/gi' file.txt              # replace all, case-insensitive
sed -i '' 's/old/new/g' file.txt         # edit file in-place (macOS)
```

### Delete lines

```bash
sed '5d' file.txt                        # delete line 5
sed '2,5d' file.txt                      # delete lines 2-5
sed '/pattern/d' file.txt                # delete lines matching pattern
sed '/^$/d' file.txt                     # delete empty lines
sed '/^#/d' file.txt                     # delete comment lines
```

### Print specific lines

```bash
sed -n '5p' file.txt                     # print only line 5
sed -n '2,5p' file.txt                   # print lines 2-5
sed -n '/error/p' file.txt              # print matching lines (like grep)
```

### Insert and append

```bash
sed '3i\new line' file.txt               # insert before line 3
sed '3a\new line' file.txt               # append after line 3
sed '3c\replaced' file.txt              # replace line 3 entirely
```

### Other tricks

```bash
sed 's|/usr/local|/opt|g' file.txt       # use | as delimiter (avoids escaping /)
sed '10s/old/new/' file.txt              # substitute only on line 10
sed '/pattern/s/^/# /' file.txt         # comment out matching lines
sed '/pattern/s/^# //' file.txt         # uncomment matching lines
sed -n '/START/,/END/p' file.txt        # print lines between two patterns
sed 's/[[:space:]]*$//' file.txt        # remove trailing whitespace
```

---

## awk

**A**ho, **W**einberger, **K**ernighan — column-based text processing.

### Basic syntax

```bash
awk 'pattern { action }' file
```

### Print columns

```bash
awk '{ print $1 }' file.txt             # print 1st column
awk '{ print $1, $3 }' file.txt         # print 1st and 3rd columns
awk '{ print $NF }' file.txt            # print last column
awk '{ print $(NF-1) }' file.txt        # print second-to-last column
```

### Custom delimiter

```bash
awk -F',' '{ print $2 }' data.csv       # CSV: print 2nd field
awk -F':' '{ print $1 }' /etc/passwd    # colon-separated
```

### Pattern matching

```bash
awk '/error/' file.log                   # print lines containing "error"
awk '$3 > 100' data.txt                  # lines where 3rd column > 100
awk '$1 == "admin"' users.txt            # lines where 1st column is "admin"
awk 'NR == 5' file.txt                   # print line 5
awk 'NR > 1' file.txt                    # skip header line
```

### Calculations

```bash
awk '{ sum += $3 } END { print sum }' file.txt            # sum a column
awk '{ sum += $3; n++ } END { print sum/n }' file.txt     # average
awk 'END { print NR }' file.txt                            # count lines
awk '{ count[$1]++ } END { for (k in count) print k, count[k] }' file.txt  # frequency count
```

### Formatting

```bash
awk '{ printf "%-15s %10d\n", $1, $2 }' file.txt          # formatted table
awk 'BEGIN { OFS="," } { print $1, $2, $3 }' file.txt     # change output separator
```

### Built-in variables

| Variable | Full meaning | Description |
|----------|-------------|-------------|
| `$0` | — | Entire line |
| `$1, $2...` | — | 1st, 2nd... field |
| `NR` | **N**umber of **R**ecords | Current line number |
| `NF` | **N**umber of **F**ields | Column count (so `$NF` = last column) |
| `FS` | **F**ield **S**eparator | Input delimiter (default: whitespace) |
| `OFS` | **O**utput **F**ield **S**eparator | Output delimiter (default: space) |

---

## df

**D**isk **F**ree — show free/used space on mounted filesystems.

```bash
df -h                                    # human-readable (GB, MB)
df -h /                                  # check root partition
df -h .                                  # check current directory's partition
df -T                                    # show filesystem type (Linux)
df -i                                    # show inode usage
```

| Flag | Description |
|------|-------------|
| `-h` | **H**uman-readable sizes |
| `-T` | Show filesystem **T**ype |
| `-i` | Show **i**node usage |

---

## du

**D**isk **U**sage — show space used by files and directories.

```bash
du -sh folder/                           # total size of a folder
du -sh *                                 # size of each item in current dir
du -h -d1 ~/Projects                     # size of each subfolder (1 level deep)
du -ah . | sort -hr | head               # top 10 biggest files (recursive)
```

| Flag | Description |
|------|-------------|
| `-h` | **H**uman-readable sizes |
| `-s` | **S**ummary (total only) |
| `-a` | **A**ll files (not just directories) |
| `-d N` | **D**epth — go only N levels |
| `-c` | Show grand total at the end |

### When to use which

| Question | Command |
|----------|---------|
| "Is my disk full?" | `df -h` |
| "What's eating space?" | `du -sh * \| sort -hr` |
| "How big is this folder?" | `du -sh folder/` |

---

## pkill

Kill processes **by name** (no need to look up the PID).

```bash
pkill python                             # graceful kill (SIGTERM)
pkill -9 python                          # force kill (SIGKILL)
pkill -f "python script.py"             # match full command line
pkill -u shubham python                  # kill user's python processes
pkill -x node                            # exact name match (won't match "nodemon")
```

### Flags reference

| Flag | Description |
|------|-------------|
| `-f` | Match against **f**ull command line |
| `-9` | Force kill (SIGKILL) |
| `-u` | Filter by **u**ser |
| `-x` | E**x**act name match |
| `-i` | Case-**i**nsensitive |

### Related commands

| Command | What it does |
|---------|-------------|
| `pgrep -fl python` | Find PIDs matching "python" (don't kill) |
| `kill 12345` | Kill by specific PID |
| `ps aux` | List all running processes |

### Signals

| Signal | Number | Behavior |
|--------|--------|----------|
| SIGTERM | 15 | Graceful shutdown (default) |
| SIGKILL | 9 | Immediate force kill |
| SIGHUP | 1 | Reload config |

---

## File Descriptors & Redirection

```bash
command > file.txt                       # redirect stdout, overwrite
command >> file.txt                      # redirect stdout, append
command 2> errors.log                    # redirect stderr to file
command 2>/dev/null                      # suppress errors
command > output.log 2>&1               # merge stderr into stdout
command &>/dev/null                      # suppress everything (shorthand)
```

| FD | Name | Description |
|----|------|-------------|
| 0 | stdin | Input |
| 1 | stdout | Normal output |
| 2 | stderr | Error output |

---

## Common Piped Commands

Real-world one-liners combining the commands above.

### Log analysis

```bash
# Count error occurrences in a log
grep -c "error" app.log

# Top 10 most frequent errors
grep -i "error" app.log | awk '{print $NF}' | sort | uniq -c | sort -nr | head

# Follow a log and highlight errors
tail -f app.log | grep --color "error"

# Search across rotated compressed logs
zgrep "timeout" /var/log/app.log.*.gz

# Extract and count HTTP status codes from access log
awk '{print $9}' access.log | sort | uniq -c | sort -nr
```

### Process management

```bash
# Find what's using port 8080
lsof -i :8080

# Top 10 processes by memory
ps aux | sort -k4 -nr | head

# Top 10 PIDs with most open files
lsof | awk '{print $2}' | sort | uniq -c | sort -nr | head

# Kill all Python processes
pkill -f python

# Find and kill process on a specific port
kill $(lsof -t -i :3000)
```

### Disk and file management

```bash
# Find what's eating disk space
du -h -d1 ~ | sort -hr | head

# Find large files (>100MB)
find . -type f -size +100M -exec ls -lh {} \;

# Find and delete .DS_Store files
find . -name ".DS_Store" -delete

# Find files modified in last 24 hours
find . -type f -mtime -1

# Count lines of code in a project
find . -name "*.py" | xargs cat | wc -l

# Better: lines per file, sorted
find . -name "*.py" -exec wc -l {} \; | sort -nr | head
```

### Text processing

```bash
# Replace string across all files
find . -name "*.py" -exec sed -i '' 's/old_func/new_func/g' {} \;

# Extract unique IPs from a log
awk '{print $1}' access.log | sort -u

# CSV: get average of 3rd column
awk -F',' '{ sum += $3; n++ } END { print sum/n }' data.csv

# Print lines between two markers
sed -n '/BEGIN/,/END/p' config.txt

# Remove duplicate lines preserving order
awk '!seen[$0]++' file.txt

# Count words in a file
cat file.txt | tr -s ' ' '\n' | sort | uniq -c | sort -nr | head
```

### System monitoring

```bash
# Check disk space
df -h | grep -v tmpfs

# Watch a command run every 2 seconds
watch -n 2 "df -h"

# Find which process is using a file
lsof /path/to/file

# List all network connections
lsof -i -P | grep LISTEN

# Find zombie processes
ps aux | awk '$8 == "Z"'
```

### Useful combo patterns

```bash
# Pattern: find + action
find . -name "*.log" -exec grep -l "error" {} \;

# Pattern: generate list → count → sort → top N
cat data.txt | awk '{print $1}' | sort | uniq -c | sort -nr | head -10

# Pattern: filter → transform → save
grep "200" access.log | awk '{print $1, $7}' | sort -u > successful_requests.txt

# Pattern: search in compressed files
zgrep "pattern" *.gz | awk -F: '{print $1}' | sort -u

# Pattern: find disk space hogs
du -ah . 2>/dev/null | sort -hr | head -20
```

---

> **Tip**: When in doubt, add `| head` at the end of any command to preview output before committing to the full result.
