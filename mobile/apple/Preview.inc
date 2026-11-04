// Quick Look preview (swipe between the files of a folder) and a plain-text editor.
// Included inside SooveeViewController.
#if !TARGET_OS_TV

static NSSet *TextTypes(void) {
    static NSSet *types;static dispatch_once_t once;
    dispatch_once(&once,^{types=[NSSet setWithArray:@[@"txt",@"text",@"md",@"markdown",@"json",@"csv",@"tsv",@"log",@"xml",@"yml",@"yaml",@"ini",@"cfg",@"conf",@"toml",@"py",@"js",@"ts",@"html",@"htm",@"css",@"sh",@"swift",@"c",@"h",@"m",@"java",@"kt",@"srt",@"sub",@"nfo"]];});
    return types;
}
- (BOOL)isText:(NSDictionary *)item { return ![item[@"directory"] boolValue]&&[TextTypes() containsObject:[item[@"name"] pathExtension].lowercaseString]; }

- (NSInteger)numberOfPreviewItemsInPreviewController:(QLPreviewController *)controller { return self.previewURLs.count; }
- (id<QLPreviewItem>)previewController:(QLPreviewController *)controller previewItemAtIndex:(NSInteger)index { return self.previewURLs[index]; }

// Opens a file in Quick Look; the other files of the folder are one swipe away.
- (void)previewItem:(NSDictionary *)item {
    [self rememberPlace:@"recentFiles" path:[self itemPath:item] name:[item[@"name"] lastPathComponent]];
    NSString *file=[self localPathFor:item];
    if(!file){
        // A file on a paired device is copied into a private cache first.
        NSString *peer=self.peer,*source=[self itemPath:item];
        UIAlertController *wait=[UIAlertController alertControllerWithTitle:item[@"name"] message:T(@"Downloading for preview…") preferredStyle:UIAlertControllerStyleAlert];
        [self presentViewController:wait animated:YES completion:^{[self call:@"preview_copy" args:@[peer,source] then:^(NSString *local){
            [wait dismissViewControllerAnimated:YES completion:^{self.previewURLs=@[[NSURL fileURLWithPath:local]];[self presentPreviewAt:0];}];}];}];
        return;}
    NSMutableArray *urls=[NSMutableArray new];NSInteger start=0;
    for(NSDictionary *entry in [self visibleFileEntries]){if([entry[@"directory"] boolValue])continue;NSString *path=[self localPathFor:entry];if(!path)continue;
        if([entry[@"name"] isEqual:item[@"name"]])start=urls.count;[urls addObject:[NSURL fileURLWithPath:path]];}
    self.previewURLs=urls;[self presentPreviewAt:start];
}
- (void)presentPreviewAt:(NSInteger)index {
    if(!self.previewURLs.count)return;
    QLPreviewController *preview=[QLPreviewController new];preview.dataSource=self;preview.currentPreviewItemIndex=index;
    [self presentViewController:preview animated:YES completion:nil];
}

// Plain-text editor: keeps the file's encoding and saves atomically.
- (void)editText:(NSDictionary *)item {
    NSString *file=[self localPathFor:item];if(!file)return;
    NSNumber *size=nil;[[NSURL fileURLWithPath:file] getResourceValue:&size forKey:NSURLFileSizeKey error:nil];
    if(size.longLongValue>4*1024*1024){[self showError:T(@"This file is too large to edit here.")];return;}
    NSStringEncoding encoding=NSUTF8StringEncoding;NSError *error=nil;NSString *text=[NSString stringWithContentsOfFile:file usedEncoding:&encoding error:&error];
    if(!text){encoding=NSUTF8StringEncoding;text=[NSString stringWithContentsOfFile:file encoding:encoding error:nil];}
    if(!text){encoding=NSWindowsCP1250StringEncoding;text=[NSString stringWithContentsOfFile:file encoding:encoding error:nil];}   // older Czech text files
    if(!text){[self showError:T(@"This file is not plain text.")];return;}
    UIViewController *editor=[UIViewController new];editor.title=item[@"name"];
    UITextView *view=[UITextView new];view.text=text;view.font=[UIFont preferredFontForTextStyle:UIFontTextStyleBody];view.adjustsFontForContentSizeCategory=YES;
    view.backgroundColor=Background();view.textColor=UIColor.labelColor;view.autocorrectionType=UITextAutocorrectionTypeNo;view.smartQuotesType=UITextSmartQuotesTypeNo;view.smartDashesType=UITextSmartDashesTypeNo;
    view.textContainerInset=UIEdgeInsetsMake(12,12,24,12);view.alwaysBounceVertical=YES;editor.view=view;
    UINavigationController *navigation=[[UINavigationController alloc]initWithRootViewController:editor];navigation.overrideUserInterfaceStyle=self.overrideUserInterfaceStyle;navigation.modalPresentationStyle=UIModalPresentationFullScreen;navigation.view.tintColor=UIColor.systemBlueColor;
    __weak UINavigationController *weakNavigation=navigation;NSString *original=text;
    editor.navigationItem.leftBarButtonItem=[[UIBarButtonItem alloc]initWithPrimaryAction:[UIAction actionWithTitle:T(@"Cancel") image:nil identifier:nil handler:^(UIAction *a){
        if([view.text isEqual:original]){[weakNavigation dismissViewControllerAnimated:YES completion:nil];return;}
        UIAlertController *ask=[UIAlertController alertControllerWithTitle:T(@"Discard changes?") message:nil preferredStyle:UIAlertControllerStyleAlert];
        [ask addAction:[UIAlertAction actionWithTitle:T(@"Keep editing") style:UIAlertActionStyleCancel handler:nil]];
        [ask addAction:[UIAlertAction actionWithTitle:T(@"Discard") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *x){[weakNavigation dismissViewControllerAnimated:YES completion:nil];}]];
        [weakNavigation presentViewController:ask animated:YES completion:nil];}]];
    UIBarButtonItem *save=[[UIBarButtonItem alloc]initWithPrimaryAction:[UIAction actionWithTitle:T(@"Save") image:nil identifier:nil handler:^(UIAction *a){
        NSError *failure=nil;
        if(![view.text writeToFile:file atomically:YES encoding:encoding error:&failure]&&![view.text writeToFile:file atomically:YES encoding:NSUTF8StringEncoding error:&failure]){
            UIAlertController *alert=[UIAlertController alertControllerWithTitle:T(@"Soovee · Error") message:failure.localizedDescription preferredStyle:UIAlertControllerStyleAlert];[alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];[weakNavigation presentViewController:alert animated:YES completion:nil];return;}
        [weakNavigation dismissViewControllerAnimated:YES completion:^{[self showFiles];}];}]];
    save.style=UIBarButtonItemStyleDone;editor.navigationItem.rightBarButtonItem=save;
    [self presentViewController:navigation animated:YES completion:^{[view becomeFirstResponder];}];
}

- (void)newTextFile {
    if([self.path isEqual:@"/"]||self.peer.length){[self showError:T(@"Choose a storage folder first.")];return;}
    NSString *path=self.path;
    UIAlertController *form=[UIAlertController alertControllerWithTitle:T(@"New text file") message:nil preferredStyle:UIAlertControllerStyleAlert];
    [form addTextFieldWithConfigurationHandler:^(UITextField *field){field.text=[T(@"New text file") stringByAppendingString:@".txt"];field.autocorrectionType=UITextAutocorrectionTypeNo;field.clearButtonMode=UITextFieldViewModeWhileEditing;
        [field addAction:[UIAction actionWithHandler:^(UIAction *a){UITextPosition *end=[field positionFromPosition:field.beginningOfDocument offset:field.text.stringByDeletingPathExtension.length];if(end)field.selectedTextRange=[field textRangeFromPosition:field.beginningOfDocument toPosition:end];}] forControlEvents:UIControlEventEditingDidBegin];}];
    [form addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    UIAlertAction *create=[UIAlertAction actionWithTitle:T(@"Create") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){NSString *name=form.textFields.firstObject.text?:@"";
        [self call:@"mutate_item" args:@[@"",path,@"newfile",name] then:^(NSString *json){[self showFiles];NSString *file=[self.filesBase stringByAppendingPathComponent:name];
            if(self.filesBase.length&&[TextTypes() containsObject:name.pathExtension.lowercaseString])dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(NSEC_PER_SEC/2)),dispatch_get_main_queue(),^{if([[NSFileManager defaultManager]fileExistsAtPath:file])[self editText:@{@"name":name,@"directory":@NO}];});}];}];
    [form addAction:create];form.preferredAction=create;[self presentViewController:form animated:YES completion:nil];
}
- (void)duplicateItem:(NSDictionary *)item {
    // A copy next to the original; the core picks a free name such as "Report (2).txt".
    [self startOperation:T(@"Duplicate") route:self.path.lastPathComponent call:@"duplicate_item" args:@[[self itemPath:item]] done:^(NSDictionary *value){[self toast:[NSString stringWithFormat:@"%@\n%@",T(@"Created"),value[@"file"]?:@""]];}];
}
#endif
